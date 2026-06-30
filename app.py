import os
import uuid
from datetime import date, datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import or_, func
from models import db, User, School, Activity, Parent, ParentActivity, EmailTemplate, EmailLog, Attachment
from brevo import send_email
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///crm.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace(
        'postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access the CRM.'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email'].strip().lower()).first()
        if user and user.check_password(request.form['password']):
            login_user(user, remember='remember' in request.form)
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    today = date.today()

    overdue = Activity.query.filter(
        Activity.follow_up_date < today,
        Activity.follow_up_complete == False
    ).join(School).order_by(Activity.follow_up_date).all()

    due_today = Activity.query.filter(
        Activity.follow_up_date == today,
        Activity.follow_up_complete == False
    ).join(School).order_by(School.name).all()

    due_soon = Activity.query.filter(
        Activity.follow_up_date > today,
        Activity.follow_up_complete == False
    ).join(School).order_by(Activity.follow_up_date).limit(10).all()

    recent = Activity.query.order_by(Activity.created_at.desc()).limit(10).all()

    stats = {
        'total_schools': School.query.count(),
        'called': School.query.join(Activity).distinct().count(),
        'won': School.query.filter_by(won=True).count(),
        'overdue': len(overdue),
    }

    return render_template('dashboard.html',
                           overdue=overdue, due_today=due_today,
                           due_soon=due_soon, recent=recent, stats=stats, today=today)


# ── Schools ───────────────────────────────────────────────────────────────────

@app.route('/schools')
@login_required
def schools():
    q = request.args.get('q', '').strip()
    phase = request.args.get('phase', '')
    tier = request.args.get('tier', '')
    club_status = request.args.get('club_status', '')
    sort = request.args.get('sort', 'name')

    query = School.query

    if q:
        query = query.filter(or_(
            School.name.ilike(f'%{q}%'),
            School.city.ilike(f'%{q}%'),
            School.headteacher.ilike(f'%{q}%'),
            School.main_email.ilike(f'%{q}%'),
        ))
    if phase:
        query = query.filter(School.phase == phase)
    if tier:
        query = query.filter(School.priority_tier == tier)
    if club_status:
        query = query.filter(School.after_school_club_status == club_status)

    sort_map = {
        'name': School.name,
        'priority': School.rating.desc(),
        'revenue': School.term_revenue.desc(),
        'pupils': School.pupils.desc(),
    }
    query = query.order_by(sort_map.get(sort, School.name))

    schools_list = query.all()

    phases = [r[0] for r in db.session.query(School.phase).distinct() if r[0]]
    tiers = [r[0] for r in db.session.query(School.priority_tier).distinct() if r[0]]
    club_statuses = [r[0] for r in db.session.query(School.after_school_club_status).distinct() if r[0]]

    return render_template('schools/index.html',
                           schools=schools_list, q=q, phase=phase,
                           tier=tier, club_status=club_status, sort=sort,
                           phases=sorted(phases), tiers=sorted(tiers),
                           club_statuses=sorted(club_statuses))


@app.route('/schools/<int:school_id>')
@login_required
def school_detail(school_id):
    school = School.query.get_or_404(school_id)
    activities = school.activities.order_by(Activity.created_at.desc()).all()
    email_logs = EmailLog.query.filter_by(school_id=school_id).order_by(EmailLog.sent_at.desc()).all()
    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    return render_template('schools/detail.html', school=school, activities=activities,
                           email_logs=email_logs, email_templates=templates,
                           today_date=date.today())


@app.route('/schools/<int:school_id>/edit', methods=['GET', 'POST'])
@login_required
def school_edit(school_id):
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        school.name = request.form['name']
        school.phone = request.form.get('phone', '')
        school.main_email = request.form.get('main_email', '')
        school.headteacher = request.form.get('headteacher', '')
        school.website = request.form.get('website', '')
        school.phase = request.form.get('phase', '')
        school.account_type = request.form.get('account_type', '')
        school.city = request.form.get('city', '')
        school.postcode = request.form.get('postcode', '')
        school.decision_maker         = request.form.get('decision_maker', '')
        school.gatekeeper             = request.form.get('gatekeeper', '')
        school.business_manager_name  = request.form.get('business_manager_name', '')
        school.business_manager_email = request.form.get('business_manager_email', '')
        school.after_school_club_status = request.form.get('after_school_club_status', '')
        school.assembly_opportunity = request.form.get('assembly_opportunity', '')
        school.summer_camp_status = request.form.get('summer_camp_status', '')
        school.digital_flyer_sent = 'digital_flyer_sent' in request.form
        school.physical_flyer_sent = 'physical_flyer_sent' in request.form
        school.won = 'won' in request.form
        school.description = request.form.get('description', '')
        school.updated_at = datetime.utcnow()
        db.session.commit()
        flash('School updated.', 'success')
        return redirect(url_for('school_detail', school_id=school.id))
    return render_template('schools/edit.html', school=school)


@app.route('/schools/new', methods=['GET', 'POST'])
@login_required
def school_new():
    if request.method == 'POST':
        school = School(
            name=request.form['name'],
            phone=request.form.get('phone', ''),
            main_email=request.form.get('main_email', ''),
            headteacher=request.form.get('headteacher', ''),
            website=request.form.get('website', ''),
            phase=request.form.get('phase', ''),
            city=request.form.get('city', ''),
            postcode=request.form.get('postcode', ''),
        )
        db.session.add(school)
        db.session.commit()
        flash('School added.', 'success')
        return redirect(url_for('school_detail', school_id=school.id))
    return render_template('schools/edit.html', school=None)


# ── Activities ────────────────────────────────────────────────────────────────

@app.route('/schools/<int:school_id>/activity/new', methods=['GET', 'POST'])
@login_required
def activity_new(school_id):
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        follow_up_raw = request.form.get('follow_up_date', '').strip()
        follow_up = datetime.strptime(follow_up_raw, '%Y-%m-%d').date() if follow_up_raw else None

        activity = Activity(
            school_id=school.id,
            user_id=current_user.id,
            type=request.form['type'],
            outcome=request.form.get('outcome', ''),
            notes=request.form.get('notes', ''),
            next_action=request.form.get('next_action', ''),
            follow_up_date=follow_up,
        )
        db.session.add(activity)

        # Update school pipeline fields from the form
        if request.form.get('club_status'):
            school.after_school_club_status = request.form['club_status']
        if request.form.get('assembly_opportunity'):
            school.assembly_opportunity = request.form['assembly_opportunity']
        if 'won' in request.form:
            school.won = True
        school.updated_at = datetime.utcnow()

        db.session.commit()
        flash('Activity logged.', 'success')
        return redirect(url_for('school_detail', school_id=school.id))
    return render_template('schools/activity_new.html', school=school)


@app.route('/activity/<int:activity_id>/complete', methods=['POST'])
@login_required
def activity_complete(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    activity.follow_up_complete = True
    db.session.commit()
    return jsonify({'ok': True})


# ── Parents ───────────────────────────────────────────────────────────────────

@app.route('/parents')
@login_required
def parents():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    enquiry = request.args.get('enquiry', '')

    query = Parent.query
    if q:
        query = query.filter(or_(
            Parent.name.ilike(f'%{q}%'),
            Parent.child_name.ilike(f'%{q}%'),
            Parent.phone.ilike(f'%{q}%'),
            Parent.email.ilike(f'%{q}%'),
        ))
    if status:
        query = query.filter(Parent.status == status)
    if enquiry:
        query = query.filter(Parent.enquiry_type == enquiry)

    parents_list = query.order_by(Parent.created_at.desc()).all()
    statuses = [r[0] for r in db.session.query(Parent.status).distinct() if r[0]]
    enquiries = [r[0] for r in db.session.query(Parent.enquiry_type).distinct() if r[0]]

    return render_template('parents/index.html', parents=parents_list, q=q,
                           status=status, enquiry=enquiry,
                           statuses=sorted(statuses), enquiries=sorted(enquiries))


@app.route('/parents/new', methods=['GET', 'POST'])
@login_required
def parent_new():
    if request.method == 'POST':
        event_raw = request.form.get('event_date', '').strip()
        event_date = datetime.strptime(event_raw, '%Y-%m-%d').date() if event_raw else None
        parent = Parent(
            name=request.form['name'],
            phone=request.form.get('phone', ''),
            email=request.form.get('email', ''),
            child_name=request.form.get('child_name', ''),
            child_age=request.form.get('child_age') or None,
            enquiry_type=request.form.get('enquiry_type', ''),
            status=request.form.get('status', 'New Enquiry'),
            event_date=event_date,
            notes=request.form.get('notes', ''),
            source=request.form.get('source', ''),
        )
        db.session.add(parent)
        db.session.commit()
        flash('Parent added.', 'success')
        return redirect(url_for('parent_detail', parent_id=parent.id))
    return render_template('parents/edit.html', parent=None)


@app.route('/parents/<int:parent_id>')
@login_required
def parent_detail(parent_id):
    parent = Parent.query.get_or_404(parent_id)
    email_logs = EmailLog.query.filter_by(parent_id=parent_id).order_by(EmailLog.sent_at.desc()).all()
    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    attachments = Attachment.query.filter_by(parent_id=parent_id).order_by(Attachment.created_at.desc()).all()
    return render_template('parents/detail.html', parent=parent,
                           email_logs=email_logs, email_templates=templates,
                           attachments=attachments)


@app.route('/parents/<int:parent_id>/edit', methods=['GET', 'POST'])
@login_required
def parent_edit(parent_id):
    parent = Parent.query.get_or_404(parent_id)
    if request.method == 'POST':
        event_raw = request.form.get('event_date', '').strip()
        parent.name = request.form['name']
        parent.phone = request.form.get('phone', '')
        parent.email = request.form.get('email', '')
        parent.child_name = request.form.get('child_name', '')
        parent.child_age = request.form.get('child_age') or None
        parent.enquiry_type = request.form.get('enquiry_type', '')
        parent.status = request.form.get('status', 'New Enquiry')
        parent.event_date = datetime.strptime(event_raw, '%Y-%m-%d').date() if event_raw else None
        parent.notes = request.form.get('notes', '')
        parent.source = request.form.get('source', '')
        parent.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Updated.', 'success')
        return redirect(url_for('parent_detail', parent_id=parent.id))
    return render_template('parents/edit.html', parent=parent)


@app.route('/parents/<int:parent_id>/activity/new', methods=['GET', 'POST'])
@login_required
def parent_activity_new(parent_id):
    parent = Parent.query.get_or_404(parent_id)
    if request.method == 'POST':
        follow_up_raw = request.form.get('follow_up_date', '').strip()
        follow_up = datetime.strptime(follow_up_raw, '%Y-%m-%d').date() if follow_up_raw else None
        act = ParentActivity(
            parent_id=parent.id,
            user_id=current_user.id,
            type=request.form['type'],
            outcome=request.form.get('outcome', ''),
            notes=request.form.get('notes', ''),
            next_action=request.form.get('next_action', ''),
            follow_up_date=follow_up,
        )
        db.session.add(act)
        if request.form.get('status'):
            parent.status = request.form['status']
        parent.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Activity logged.', 'success')
        return redirect(url_for('parent_detail', parent_id=parent.id))
    return render_template('parents/activity_new.html', parent=parent)


# ── Attachments ───────────────────────────────────────────────────────────────

@app.route('/parents/<int:parent_id>/upload', methods=['POST'])
@login_required
def attachment_upload(parent_id):
    parent = Parent.query.get_or_404(parent_id)
    if 'file' not in request.files or request.files['file'].filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('parent_detail', parent_id=parent_id))

    f = request.files['file']
    if not allowed_file(f.filename):
        flash('File type not allowed. Use PDF, Word, or image files.', 'danger')
        return redirect(url_for('parent_detail', parent_id=parent_id))

    ext = f.filename.rsplit('.', 1)[1].lower()
    stored_name = f'{uuid.uuid4().hex}.{ext}'
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], stored_name))

    att = Attachment(
        parent_id=parent.id,
        user_id=current_user.id,
        original_filename=secure_filename(f.filename),
        stored_filename=stored_name,
        file_size=os.path.getsize(os.path.join(app.config['UPLOAD_FOLDER'], stored_name)),
    )
    db.session.add(att)
    db.session.commit()
    flash(f'"{f.filename}" uploaded.', 'success')
    return redirect(url_for('parent_detail', parent_id=parent_id))


@app.route('/attachments/<int:attachment_id>/download')
@login_required
def attachment_download(attachment_id):
    from flask import send_from_directory
    att = Attachment.query.get_or_404(attachment_id)
    return send_from_directory(app.config['UPLOAD_FOLDER'], att.stored_filename,
                               as_attachment=False,
                               download_name=att.original_filename)


@app.route('/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def attachment_delete(attachment_id):
    att = Attachment.query.get_or_404(attachment_id)
    parent_id = att.parent_id
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], att.stored_filename))
    except FileNotFoundError:
        pass
    db.session.delete(att)
    db.session.commit()
    flash('File deleted.', 'success')
    return redirect(url_for('parent_detail', parent_id=parent_id))


# ── Email ─────────────────────────────────────────────────────────────────────

@app.route('/email/send', methods=['POST'])
@login_required
def email_send():
    school_id = request.form.get('school_id', type=int)
    parent_id = request.form.get('parent_id', type=int)
    to_email = request.form.get('to_email', '').strip()
    to_name = request.form.get('to_name', '').strip()
    subject = request.form.get('subject', '').strip()
    body_html = request.form.get('body_html', '').strip()
    template_name = request.form.get('template_name', '')

    if not to_email or not subject or not body_html:
        flash('Email address, subject and body are all required.', 'danger')
        return redirect(request.referrer)

    message_id, error = send_email(to_email, to_name, subject, body_html)

    log = EmailLog(
        school_id=school_id,
        parent_id=parent_id,
        user_id=current_user.id,
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body_html=body_html,
        template_name=template_name,
        brevo_message_id=message_id,
        status='sent' if message_id else 'error',
    )
    db.session.add(log)
    db.session.commit()

    if error:
        flash(f'Failed to send: {error}', 'danger')
    else:
        flash(f'Email sent to {to_email}.', 'success')

    if school_id:
        return redirect(url_for('school_detail', school_id=school_id))
    if parent_id:
        return redirect(url_for('parent_detail', parent_id=parent_id))
    return redirect(request.referrer)


@app.route('/email/templates', methods=['GET', 'POST'])
@login_required
def email_templates():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            t = EmailTemplate.query.get_or_404(request.form.get('template_id', type=int))
            db.session.delete(t)
            db.session.commit()
            flash('Template deleted.', 'success')
        else:
            tid = request.form.get('template_id', type=int)
            if tid:
                t = EmailTemplate.query.get_or_404(tid)
            else:
                t = EmailTemplate()
                db.session.add(t)
            t.name = request.form['name']
            t.subject = request.form['subject']
            t.body_html = request.form['body_html']
            db.session.commit()
            flash('Template saved.', 'success')
        return redirect(url_for('email_templates'))

    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    return render_template('email/templates.html', templates=templates)


@app.route('/email/templates/<int:template_id>/json')
@login_required
def email_template_json(template_id):
    t = EmailTemplate.query.get_or_404(template_id)
    return jsonify({'subject': t.subject, 'body_html': t.body_html, 'name': t.name})


@app.route('/email/log/<int:log_id>/delete', methods=['POST'])
@login_required
def email_log_delete(log_id):
    em = EmailLog.query.get_or_404(log_id)
    school_id = em.school_id
    parent_id = em.parent_id
    db.session.delete(em)
    db.session.commit()
    if school_id:
        return redirect(url_for('school_detail', school_id=school_id))
    return redirect(url_for('parent_detail', parent_id=parent_id))


@app.route('/email/log/<int:log_id>/json')
@login_required
def email_log_json(log_id):
    em = EmailLog.query.get_or_404(log_id)
    return jsonify({
        'to_email': em.to_email,
        'to_name': em.to_name or '',
        'subject': em.subject or '',
        'body_html': em.body_html or '',
        'template_name': em.template_name or '',
    })


@app.route('/webhooks/brevo', methods=['POST'])
def brevo_webhook():
    """Receives delivery/open/bounce events from Brevo."""
    events = request.get_json(force=True, silent=True)
    if not events:
        return '', 200
    if isinstance(events, dict):
        events = [events]
    for event in events:
        message_id = event.get('message-id') or event.get('messageId', '')
        event_type = event.get('event', '')
        if not message_id:
            continue
        log = EmailLog.query.filter_by(brevo_message_id=message_id).first()
        if not log:
            continue
        ts = datetime.utcnow()
        if event_type == 'delivered' and not log.delivered_at:
            log.status = 'delivered'
            log.delivered_at = ts
        elif event_type in ('opened', 'open') and not log.opened_at:
            log.status = 'opened'
            log.opened_at = ts
        elif event_type in ('bounced', 'hard_bounce', 'soft_bounce') and not log.bounced_at:
            log.status = 'bounced'
            log.bounced_at = ts
        db.session.commit()
    return '', 200


# ── Data Import ───────────────────────────────────────────────────────────────

@app.route('/admin/import', methods=['GET', 'POST'])
@login_required
def admin_import():
    if request.method == 'POST':
        if 'file' not in request.files or request.files['file'].filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('admin_import'))
        f = request.files['file']
        import tempfile, pandas as pd
        from import_zoho import import_file
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
            f.save(tmp.name)
            import_file(tmp.name)
        flash('Import complete.', 'success')
        return redirect(url_for('schools'))
    return render_template('admin/import.html')


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if request.method == 'POST':
        existing = User.query.filter_by(email=request.form['email'].strip().lower()).first()
        if existing:
            flash('Email already exists.', 'danger')
        else:
            user = User(
                name=request.form['name'],
                email=request.form['email'].strip().lower(),
            )
            user.set_password(request.form['password'])
            db.session.add(user)
            db.session.commit()
            flash(f'User {user.name} created.', 'success')
    users = User.query.order_by(User.name).all()
    return render_template('auth/users.html', users=users)


# ── Init ──────────────────────────────────────────────────────────────────────

def migrate_db():
    """Add any missing columns without dropping data."""
    migrations = [
        ('schools', 'business_manager_name',  'VARCHAR(200)'),
        ('schools', 'business_manager_email', 'VARCHAR(150)'),
    ]
    with db.engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(db.text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'))
                conn.commit()
            except Exception:
                pass  # column already exists


def create_tables():
    with app.app_context():
        db.create_all()
        migrate_db()
        if not User.query.first():
            admin = User(name='Admin', email='admin@inventorsleague.co.uk')
            admin.set_password('changeme123')
            db.session.add(admin)
            db.session.commit()
            print('Created default admin user: admin@inventorsleague.co.uk / changeme123')


if __name__ == '__main__':
    create_tables()
    app.run(debug=True)
