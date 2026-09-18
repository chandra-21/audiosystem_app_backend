# backend/routers/playlist.py - NO AUTH VERSION
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import shutil
from pathlib import Path
import models, schemas

from database import SessionLocal
from services.audio_service import get_audio_service

# Dependency untuk mendapatkan DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(prefix="/music", tags=["playlist"])
audio_service = get_audio_service()

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =====================================================
# MUSIC MANAGEMENT ENDPOINTS
# =====================================================

@router.post("/upload", response_model=schemas.MusicResponse)
async def upload_music(
    file: UploadFile = File(...),
    uploaded_by: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Upload file musik baru
    File akan otomatis masuk ke shared playlist
    """
    # Validasi tipe file
    allowed_extensions = ['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac']
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Format file tidak didukung. Gunakan: {', '.join(allowed_extensions)}"
        )
    
    # Buat nama file unik jika sudah ada
    base_filename = file.filename
    file_path = os.path.join(UPLOAD_DIR, base_filename)
    counter = 1
    
    while os.path.exists(file_path):
        name, ext = os.path.splitext(base_filename)
        new_filename = f"{name}_{counter}{ext}"
        file_path = os.path.join(UPLOAD_DIR, new_filename)
        counter += 1
    
    try:
        # Simpan file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Dapatkan durasi musik
        duration = audio_service.get_audio_duration(file_path)
        
        # Simpan ke database
        music = models.Music(
            title=os.path.splitext(os.path.basename(file_path))[0],
            filename=os.path.basename(file_path),
            filepath=file_path,
            duration=duration,
            uploaded_by=uploaded_by
        )
        
        db.add(music)
        db.commit()
        db.refresh(music)
        
        # Refresh playlist
        audio_service.refresh_playlist()
        
        return music
        
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@router.get("/list/all")
async def list_all_music(db: Session = Depends(get_db)):
    """Dapatkan semua musik dari database"""
    music_list = db.query(models.Music).order_by(
        models.Music.created_at.desc()
    ).all()
    
    return music_list


@router.delete("/{music_id}")
async def delete_music(
    music_id: int,
    db: Session = Depends(get_db)
):
    """Hapus musik berdasarkan ID database"""
    music = db.query(models.Music).filter(models.Music.id == music_id).first()
    
    if not music:
        raise HTTPException(status_code=404, detail="Musik tidak ditemukan")
    
    try:
        filename = os.path.basename(music.filepath) if music.filepath else music.filename
        
        # Hapus file dan refresh playlist
        audio_service.delete_music(filename)
        
        # Hapus dari database
        db.delete(music)
        db.commit()
        
        return {"message": "Musik berhasil dihapus", "deleted_id": music_id}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting music: {str(e)}")


# =====================================================
# PLAYBACK CONTROL ENDPOINTS
# =====================================================

@router.post("/play/index/{index}")
async def play_by_index(index: int):
    """Putar musik berdasarkan index di playlist (0-based)"""
    try:
        playlist = audio_service.get_playlist()
        
        if index < 0 or index >= len(playlist):
            raise HTTPException(
                status_code=400, 
                detail=f"Index tidak valid. Playlist memiliki {len(playlist)} lagu (index: 0-{len(playlist)-1})"
            )
        
        audio_service.play_by_index(index)
        status = audio_service.get_status()
        
        return {
            "message": "Musik sedang diputar",
            "music_id": index,
            "index": index,
            "title": status["current_music"]["title"] if status["current_music"] else None,
            "filename": status["current_music"]["filename"] if status["current_music"] else None,
            "duration": status["duration"],
            "playlist_count": status["playlist_count"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error playing music: {str(e)}")


@router.post("/play/{music_id}")
async def play_music(
    music_id: int,
    db: Session = Depends(get_db)
):
    """Putar musik berdasarkan ID database"""
    music = db.query(models.Music).filter(models.Music.id == music_id).first()
    
    if not music:
        raise HTTPException(status_code=404, detail="Musik tidak ditemukan di database")
    
    filename = os.path.basename(music.filepath) if music.filepath else music.filename
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404, 
            detail=f"File musik tidak ditemukan di server: {filename}"
        )
    
    try:
        audio_service.refresh_playlist()
        audio_service.play_by_filename(filename)
        
        status = audio_service.get_status()
        
        return {
            "message": "Musik sedang diputar",
            "music_id": music_id,
            "title": music.title,
            "filename": filename,
            "duration": status["duration"],
            "playlist_count": status["playlist_count"]
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error playing music: {str(e)}")


@router.post("/pause")
async def pause_music():
    """Pause musik yang sedang diputar"""
    if not audio_service.is_playing:
        raise HTTPException(status_code=400, detail="Tidak ada musik yang sedang diputar")
    
    audio_service.pause()
    return {"message": "Musik di-pause"}


@router.post("/resume")
async def resume_music():
    """Resume musik yang di-pause"""
    if not audio_service.is_paused:
        raise HTTPException(status_code=400, detail="Musik tidak dalam status pause")
    
    audio_service.resume()
    return {"message": "Musik dilanjutkan"}


@router.post("/stop")
async def stop_music():
    """Stop musik yang sedang diputar"""
    audio_service.stop()
    return {"message": "Musik dihentikan"}


@router.post("/next")
async def next_music(db: Session = Depends(get_db)):
    """Putar musik berikutnya dalam playlist"""
    try:
        audio_service.skip_next()
        
        if audio_service.current_music:
            filename = audio_service.current_music["filename"]
            music = db.query(models.Music).filter(models.Music.filename == filename).first()
            music_id = music.id if music else None
            
            return {
                "message": "Memutar musik berikutnya",
                "music_id": music_id,
                "title": audio_service.current_music["title"],
                "filename": filename
            }
        else:
            return {"message": "Playlist selesai", "music_id": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/previous")
async def previous_music(db: Session = Depends(get_db)):
    """Putar musik sebelumnya dalam playlist"""
    try:
        audio_service.skip_previous()
        
        if audio_service.current_music:
            filename = audio_service.current_music["filename"]
            music = db.query(models.Music).filter(models.Music.filename == filename).first()
            music_id = music.id if music else None
            
            return {
                "message": "Memutar musik sebelumnya",
                "music_id": music_id,
                "title": audio_service.current_music["title"],
                "filename": filename
            }
        else:
            return {"message": "Tidak ada musik sebelumnya", "music_id": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/volume")
async def set_volume(volume: int = Query(..., ge=0, le=100, description="Volume 0-100")):
    """Set volume player (0-100)"""
    audio_service.set_volume(volume)
    return {"message": f"Volume diset ke {volume}", "volume": volume}


@router.post("/seek")
async def seek_position(position: float = Query(..., ge=0, description="Posisi dalam detik")):
    """Pindah ke posisi tertentu dalam detik"""
    if not audio_service.is_playing:
        raise HTTPException(status_code=400, detail="Tidak ada musik yang sedang diputar")
    
    if position > audio_service.duration:
        raise HTTPException(
            status_code=400, 
            detail=f"Posisi melebihi durasi musik ({audio_service.duration:.1f}s)"
        )
    
    audio_service.seek(position)
    return {"message": f"Pindah ke detik {position:.1f}", "position": position}


@router.get("/status", response_model=schemas.PlayerStatusResponse)
async def get_status():
    """Dapatkan status player saat ini"""
    status = audio_service.get_status()
    return status


@router.get("/current")
async def get_current_music(db: Session = Depends(get_db)):
    """Dapatkan informasi musik yang sedang diputar"""
    if not audio_service.current_music:
        return {"message": "Tidak ada musik yang sedang diputar", "music": None}
    
    current = audio_service.current_music
    filename = current.get("filename")
    
    music = db.query(models.Music).filter(models.Music.filename == filename).first()
    
    return {
        "music": {
            "id": music.id if music else None,
            "title": current["title"],
            "filename": filename,
            "filepath": current["filepath"],
            "duration": audio_service.duration,
            "position": audio_service.position,
            "is_playing": audio_service.is_playing,
            "is_paused": audio_service.is_paused,
            "volume": audio_service.volume,
            "uploaded_by": music.uploaded_by if music else None,
            "created_at": str(music.created_at) if music else None
        }
    }


@router.get("/playlist")
async def get_playlist(db: Session = Depends(get_db)):
    """Dapatkan shared playlist dengan ID dari database"""
    playlist = audio_service.get_playlist()
    
    playlist_with_id = []
    for idx, music in enumerate(playlist):
        db_music = db.query(models.Music).filter(
            models.Music.filename == music["filename"]
        ).first()
        
        playlist_with_id.append({
            "id": db_music.id if db_music else None,
            "title": music["title"],
            "filename": music["filename"],
            "filepath": music["filepath"],
            "index": idx
        })
    
    return {
        "playlist": playlist_with_id,
        "count": len(playlist_with_id),
        "current_index": audio_service.current_index,
        "repeat_mode": audio_service.repeat_mode
    }


@router.post("/playlist/refresh")
async def refresh_playlist():
    """Manual refresh playlist dari folder"""
    audio_service.refresh_playlist()
    playlist = audio_service.get_playlist()
    
    return {
        "message": "Playlist di-refresh",
        "count": len(playlist),
        "playlist": playlist
    }


@router.get("/playlist/debug")
async def debug_playlist(db: Session = Depends(get_db)):
    """Debug endpoint untuk cek sinkronisasi database vs folder"""
    audio_service.refresh_playlist()
    playlist = audio_service.get_playlist()
    
    db_files = db.query(models.Music).all()
    
    physical_files = []
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            filepath = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(filepath):
                physical_files.append(filename)
    
    db_filenames = {m.filename for m in db_files}
    playlist_filenames = {p["filename"] for p in playlist}
    physical_filenames = set(physical_files)
    
    return {
        "upload_dir": UPLOAD_DIR,
        "stats": {
            "database_count": len(db_files),
            "playlist_count": len(playlist),
            "physical_count": len(physical_files)
        },
        "database_files": [{"id": m.id, "filename": m.filename, "exists": os.path.exists(os.path.join(UPLOAD_DIR, m.filename))} for m in db_files],
        "playlist_files": [p["filename"] for p in playlist],
        "physical_files": physical_files,
        "issues": {
            "in_db_not_in_folder": list(db_filenames - physical_filenames),
            "in_folder_not_in_db": list(physical_filenames - db_filenames),
            "in_db_not_in_playlist": list(db_filenames - playlist_filenames)
        }
    }


@router.post("/playlist/sync")
async def sync_playlist(db: Session = Depends(get_db)):
    """
    Sinkronisasi database dengan folder fisik
    - Hapus entry database untuk file yang tidak ada
    - Tambahkan entry database untuk file yang belum terdaftar
    """
    audio_service.refresh_playlist()
    
    physical_files = set()
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            filepath = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(filepath):
                ext = os.path.splitext(filename)[1].lower()
                if ext in audio_service.SUPPORTED_FORMATS:
                    physical_files.add(filename)
    
    db_files = db.query(models.Music).all()
    db_filenames = {m.filename: m for m in db_files}
    
    # Hapus entry database untuk file yang tidak ada
    removed = []
    for music in db_files:
        if music.filename not in physical_files:
            db.delete(music)
            removed.append(music.filename)
    
    # Tambahkan entry database untuk file yang belum terdaftar
    added = []
    for filename in physical_files:
        if filename not in db_filenames:
            filepath = os.path.join(UPLOAD_DIR, filename)
            duration = audio_service.get_audio_duration(filepath)
            
            new_music = models.Music(
                title=os.path.splitext(filename)[0],
                filename=filename,
                filepath=filepath,
                duration=duration,
                uploaded_by="system"
            )
            db.add(new_music)
            added.append(filename)
    
    db.commit()
    audio_service.refresh_playlist()
    
    return {
        "message": "Sinkronisasi selesai",
        "removed": removed,
        "added": added,
        "total_files": len(physical_files)
    }


@router.post("/repeat")
async def set_repeat_mode(mode: str = Query(..., regex="^(all|one|off)$", description="Mode: all, one, off")):
    """Set repeat mode: all, one, off"""
    audio_service.set_repeat_mode(mode)
    return {"message": f"Repeat mode: {mode}", "repeat_mode": mode}