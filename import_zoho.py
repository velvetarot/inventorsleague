"""
Run once to import Zoho Accounts export into the CRM database.
Usage: python import_zoho.py path/to/Accounts_export.xlsx
"""
import sys
import math
from datetime import datetime
import pandas as pd
from app import app, create_tables
from models import db, School


def clean(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return str(val).strip() or None


def clean_float(val):
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def clean_int(val):
    f = clean_float(val)
    return int(f) if f is not None else None


def clean_bool(val):
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('true', '1', 'yes')


def clean_date(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, datetime):
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def import_file(path):
    df = pd.read_excel(path, dtype={'Record Id': str})
    df = df.dropna(subset=['Account Name'])
    print(f"Found {len(df)} named rows in {path}")

    with app.app_context():
        create_tables()
        created = 0
        updated = 0

        for _, row in df.iterrows():
            zoho_id = clean(row.get('Record Id'))

            school = School.query.filter_by(zoho_id=zoho_id).first() if zoho_id else None
            if not school:
                school = School()
                db.session.add(school)
                created += 1
            else:
                updated += 1

            school.zoho_id = zoho_id
            school.name = clean(row.get('Account Name')) or 'Unknown'
            school.phone = clean(row.get('Phone'))
            school.website = clean(row.get('Website'))
            school.main_email = clean(row.get('Main Email'))
            school.headteacher = clean(row.get('Headteacher'))
            school.account_type = clean(row.get('Account Type'))
            school.phase = clean(row.get('Phase'))
            school.pupils = clean_int(row.get('Pupils'))
            school.fsm_percent = clean_float(row.get('FSM %'))
            school.affluence_score = clean_float(row.get('Affluence Score'))
            school.est_club_pupils_low = clean_int(row.get('Est Club Pupils Low'))
            school.est_club_pupils_high = clean_int(row.get('Est Club Pupils High'))
            school.term_revenue = clean_float(row.get('Term Revenue (£)'))
            school.term_profit = clean_float(row.get('Term Profit (£)'))
            school.annual_revenue = clean_float(row.get('Annual Revenue'))
            school.rating = clean_float(row.get('Rating'))
            school.final_score = clean_float(row.get('Final Score'))
            school.priority_tier = clean(row.get('Priority Tier'))
            school.call_action = clean(row.get('Call Action'))
            school.after_school_club_status = clean(row.get('After-School Club Status'))
            school.assembly_opportunity = clean(row.get('Assembly Opportunity'))
            school.assembly_date = clean_date(row.get('Assembly Date'))
            school.summer_camp_status = clean(row.get('Summer Camp Status'))
            school.decision_maker = clean(row.get('Decision Maker'))
            school.gatekeeper = clean(row.get('Gatekeeper'))
            school.won = clean_bool(row.get('Won?'))
            school.digital_flyer_sent = clean_bool(row.get('Digital Flyer Sent'))
            school.physical_flyer_sent = clean_bool(row.get('Physical Flyer Sent'))
            school.description = clean(row.get('Description'))

            # Address
            city = clean(row.get('Billing Address - City'))
            postcode = clean(row.get('Billing Address - Zip / Postal Code'))
            street = clean(row.get('Billing Address - Street Address'))
            school.city = city
            school.postcode = postcode
            school.billing_address = ', '.join(filter(None, [street, city, postcode]))

        db.session.commit()
        print(f"Done. Created: {created}, Updated: {updated}")


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'Accounts_1782811406287.xlsx'
    import_file(path)
