# backend/migrations/001_capability_system.py

import sqlite3
import os
from datetime import datetime

# Database path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'iot_audio.db')

def backup_database():
    """Create backup before migration"""
    backup_path = DB_PATH + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"✅ Backup created: {backup_path}")
    return backup_path

def migrate():
    """Run migration to capability system"""
    
    print("🚀 Starting migration to capability system...")
    print("=" * 60)
    
    # Backup first
    backup_path = backup_database()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. Create rooms table
        print("\n📦 Creating rooms table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id VARCHAR(100) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                icon VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("   ✅ Done")
        
        # 2. Add room_id column to smartbuddy_devices
        print("\n📦 Adding room_id to smartbuddy_devices...")
        cursor.execute("PRAGMA table_info(smartbuddy_devices)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'room_id' not in columns:
            cursor.execute("ALTER TABLE smartbuddy_devices ADD COLUMN room_id VARCHAR(100)")
            print("   ✅ room_id column added")
        else:
            print("   ⏭️  room_id column already exists")
        
        # 3. Create device_capabilities table
        print("\n📦 Creating device_capabilities table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id VARCHAR(100) NOT NULL,
                capability_type VARCHAR(50) NOT NULL,
                capability_id VARCHAR(100) UNIQUE NOT NULL,
                name VARCHAR(100),
                config TEXT,
                enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES smartbuddy_devices(device_id) ON DELETE CASCADE
            )
        """)
        print("   ✅ Done")
        
        # 4. Migrate existing devices to capabilities
        print("\n📦 Migrating existing devices to capability system...")
        
        cursor.execute("SELECT device_id, name FROM smartbuddy_devices")
        existing_devices = cursor.fetchall()
        
        if existing_devices:
            for device_id, name in existing_devices:
                # Set room_id = device_id if null
                cursor.execute("""
                    UPDATE smartbuddy_devices 
                    SET room_id = ? 
                    WHERE device_id = ? AND room_id IS NULL
                """, (device_id, device_id))
                
                # Create AC capability
                ac_cap_id = f"{device_id}_ac"
                cursor.execute("""
                    INSERT OR IGNORE INTO device_capabilities 
                    (device_id, capability_type, capability_id, name, config, enabled)
                    VALUES (?, 'ac', ?, 'AC Control', '{"pin": 27}', 1)
                """, (device_id, ac_cap_id))
                
                # Create Lamp capability
                lamp_cap_id = f"{device_id}_lamp"
                cursor.execute("""
                    INSERT OR IGNORE INTO device_capabilities 
                    (device_id, capability_type, capability_id, name, config, enabled)
                    VALUES (?, 'lamp', ?, 'Lamp Control', '{"relay_pin": 25, "pir_pin": 13}', 1)
                """, (device_id, lamp_cap_id))
                
                print(f"   ✅ Migrated device: {device_id}")
        else:
            print("   ⏭️  No existing devices to migrate")
        
        # 5. Migrate AC states
        print("\n📦 Migrating AC states...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS smartbuddy_ac_state_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capability_id VARCHAR(100) UNIQUE NOT NULL,
                power BOOLEAN DEFAULT 0,
                mode VARCHAR(20) DEFAULT 'cool',
                temperature INTEGER DEFAULT 25,
                fan_speed VARCHAR(20) DEFAULT 'auto',
                swing_vertical VARCHAR(10) DEFAULT 'off',
                swing_horizontal VARCHAR(10) DEFAULT 'off',
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (capability_id) REFERENCES device_capabilities(capability_id) ON DELETE CASCADE
            )
        """)
        
        # Migrate existing AC state data
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='smartbuddy_ac_state'")
        if cursor.fetchone():
            cursor.execute("SELECT * FROM smartbuddy_ac_state")
            ac_states = cursor.fetchall()
            
            if ac_states:
                cursor.execute("PRAGMA table_info(smartbuddy_ac_state)")
                ac_columns = [col[1] for col in cursor.fetchall()]
                device_id_idx = ac_columns.index('device_id')
                
                for row in ac_states:
                    device_id = row[device_id_idx]
                    capability_id = f"{device_id}_ac"
                    
                    power = row[ac_columns.index('power')] if 'power' in ac_columns else 0
                    mode = row[ac_columns.index('mode')] if 'mode' in ac_columns else 'cool'
                    temp = row[ac_columns.index('temperature')] if 'temperature' in ac_columns else 25
                    fan = row[ac_columns.index('fan_speed')] if 'fan_speed' in ac_columns else 'auto'
                    swing_v = row[ac_columns.index('swing_vertical')] if 'swing_vertical' in ac_columns else 'off'
                    swing_h = row[ac_columns.index('swing_horizontal')] if 'swing_horizontal' in ac_columns else 'off'
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO smartbuddy_ac_state_new 
                        (capability_id, power, mode, temperature, fan_speed, swing_vertical, swing_horizontal)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (capability_id, power, mode, temp, fan, swing_v, swing_h))
                
                print(f"   ✅ Migrated {len(ac_states)} AC states")
            else:
                print("   ⏭️  No AC states to migrate")
            
            cursor.execute("DROP TABLE smartbuddy_ac_state")
        
        cursor.execute("ALTER TABLE smartbuddy_ac_state_new RENAME TO smartbuddy_ac_state")
        print("   ✅ AC states table updated")
        
        # 6. Migrate Lamp states
        print("\n📦 Migrating Lamp states...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS smartbuddy_lamp_state_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capability_id VARCHAR(100) UNIQUE NOT NULL,
                power BOOLEAN DEFAULT 0,
                mode VARCHAR(20) DEFAULT 'manual',
                pir_motion BOOLEAN DEFAULT 0,
                pir_timeout INTEGER DEFAULT 300,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (capability_id) REFERENCES device_capabilities(capability_id) ON DELETE CASCADE
            )
        """)
        
        # Migrate existing Lamp state data
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='smartbuddy_lamp_state'")
        if cursor.fetchone():
            cursor.execute("SELECT * FROM smartbuddy_lamp_state")
            lamp_states = cursor.fetchall()
            
            if lamp_states:
                cursor.execute("PRAGMA table_info(smartbuddy_lamp_state)")
                lamp_columns = [col[1] for col in cursor.fetchall()]
                device_id_idx = lamp_columns.index('device_id')
                
                for row in lamp_states:
                    device_id = row[device_id_idx]
                    capability_id = f"{device_id}_lamp"
                    
                    power = row[lamp_columns.index('power')] if 'power' in lamp_columns else 0
                    mode = row[lamp_columns.index('mode')] if 'mode' in lamp_columns else 'manual'
                    pir_motion = row[lamp_columns.index('pir_motion')] if 'pir_motion' in lamp_columns else 0
                    pir_timeout = row[lamp_columns.index('pir_timeout')] if 'pir_timeout' in lamp_columns else 300
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO smartbuddy_lamp_state_new 
                        (capability_id, power, mode, pir_motion, pir_timeout)
                        VALUES (?, ?, ?, ?, ?)
                    """, (capability_id, power, mode, pir_motion, pir_timeout))
                
                print(f"   ✅ Migrated {len(lamp_states)} Lamp states")
            else:
                print("   ⏭️  No Lamp states to migrate")
            
            cursor.execute("DROP TABLE smartbuddy_lamp_state")
        
        cursor.execute("ALTER TABLE smartbuddy_lamp_state_new RENAME TO smartbuddy_lamp_state")
        print("   ✅ Lamp states table updated")
        
        # 7. Create indexes
        print("\n📦 Creating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_room ON smartbuddy_devices(room_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capabilities_device ON device_capabilities(device_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capabilities_type ON device_capabilities(capability_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ac_state_capability ON smartbuddy_ac_state(capability_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lamp_state_capability ON smartbuddy_lamp_state(capability_id)")
        print("   ✅ Done")
        
        # Commit changes
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print(f"📁 Backup saved at: {backup_path}")
        print("=" * 60)
        
    except Exception as e:
        conn.rollback()
        print("\n" + "=" * 60)
        print(f"❌ Migration failed: {e}")
        print(f"💾 Database backup available at: {backup_path}")
        print("=" * 60)
        raise
    
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()