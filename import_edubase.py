"""
Import schools from Edubase XLSX for Barnet, Harrow and Hertfordshire.
Run locally: python3 import_edubase.py
"""
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

XLSX_PATH = '/Users/howardgrahame/Dropbox/Inventors League Limited/2026 Edubase for Invetor League.xlsx'
TARGET_LAS = ['Barnet', 'Harrow', 'Hertfordshire']
TARGET_PHASES = ['Primary', 'Middle deemed primary', 'All-through']

# ── Load & filter ──────────────────────────────────────────────────────────────
df = pd.read_excel(XLSX_PATH, dtype=str)
df = df.fillna('')

filtered = df[
    df['LA (name)'].isin(TARGET_LAS) &
    df['PhaseOfEducation (name)'].isin(TARGET_PHASES) &
    (df['EstablishmentStatus (name)'] == 'Open')
].copy()

print(f'Schools to import: {len(filtered)}')

# ── Connect to Railway DB ──────────────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    print('ERROR: DATABASE_URL not set. Add it to .env')
    exit(1)

DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://')

from sqlalchemy import create_engine, text
engine = create_engine(DATABASE_URL)

imported = 0
skipped = 0
errors = 0

with engine.connect() as conn:
    for _, row in filtered.iterrows():
        urn = row.get('URN', '').strip()
        name = row.get('EstablishmentName', '').strip()
        if not name:
            continue

        # Build headteacher name
        head_title = row.get('HeadTitle (name)', '').strip()
        head_first = row.get('HeadFirstName', '').strip()
        head_last  = row.get('HeadLastName', '').strip()
        headteacher = ' '.join(filter(None, [head_title, head_first, head_last])) or None

        # Phone — clean up scientific notation
        phone_raw = row.get('TelephoneNum', '').strip()
        try:
            phone = str(int(float(phone_raw))) if phone_raw and phone_raw not in ('', 'nan') else None
            if phone and len(phone) == 10:
                phone = '0' + phone
        except Exception:
            phone = None

        pupils_raw = row.get('NumberOfPupils', '').strip()
        try:
            pupils = int(float(pupils_raw)) if pupils_raw else None
        except Exception:
            pupils = None

        fsm_raw = row.get('PercentageFSM', '').strip()
        try:
            fsm = float(fsm_raw) if fsm_raw else None
        except Exception:
            fsm = None

        phase = row.get('PhaseOfEducation (name)', '').strip() or None
        postcode = row.get('Postcode', '').strip() or None
        city = row.get('Town', '').strip() or None
        website = row.get('SchoolWebsite', '').strip() or None

        # Street address
        street_parts = [row.get('Street',''), row.get('Locality',''), row.get('Address3','')]
        billing_address = ', '.join(p.strip() for p in street_parts if p.strip()) or None

        # Check if already exists by URN (zoho_id field) or name+postcode
        existing = conn.execute(
            text("SELECT id FROM schools WHERE zoho_id = :urn OR (name = :name AND postcode = :postcode)"),
            {'urn': f'EDU-{urn}', 'name': name, 'postcode': postcode or ''}
        ).fetchone()

        if existing:
            skipped += 1
            continue

        try:
            conn.execute(text("""
                INSERT INTO schools (
                    name, phone, website, headteacher, phase, pupils, fsm_percent,
                    city, postcode, billing_address, zoho_id, created_at, updated_at
                ) VALUES (
                    :name, :phone, :website, :headteacher, :phase, :pupils, :fsm,
                    :city, :postcode, :billing_address, :zoho_id, NOW(), NOW()
                )
            """), {
                'name': name,
                'phone': phone,
                'website': website,
                'headteacher': headteacher,
                'phase': phase,
                'pupils': pupils,
                'fsm': fsm,
                'city': city,
                'postcode': postcode,
                'billing_address': billing_address,
                'zoho_id': f'EDU-{urn}',
            })
            conn.commit()
            imported += 1
            if imported % 50 == 0:
                print(f'  {imported} imported...')
        except Exception as e:
            errors += 1
            print(f'  ERROR on {name}: {e}')

print(f'\nDone: {imported} imported, {skipped} skipped (already exist), {errors} errors')
