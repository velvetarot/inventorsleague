import os
import uuid
import io
from datetime import date, datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import or_, func
from models import db, User, School, Activity, Parent, ParentActivity, EmailTemplate, EmailLog, Attachment, Message, Booking
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


# ── Role decorators ───────────────────────────────────────────────────────────

from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash('Manager access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def delete_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_delete:
            flash('You do not have permission to delete records.', 'danger')
            return redirect(request.referrer or url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Online presence ───────────────────────────────────────────────────────────

@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db.session.commit()


@app.context_processor
def inject_online_users():
    if current_user.is_authenticated:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        online = User.query.filter(
            User.last_seen >= cutoff,
            User.id != current_user.id
        ).all()
        unread = Message.query.filter_by(recipient_id=current_user.id, read=False).count()
        return {'online_users': online, 'unread_count': unread}
    return {'online_users': [], 'unread_count': 0}


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


# ── Today's Activity ──────────────────────────────────────────────────────────

@app.route('/today')
@login_required
def today_activity():
    today = date.today()
    activities = Activity.query.filter(
        db.func.date(Activity.created_at) == today
    ).join(School).order_by(Activity.created_at.desc()).all()
    emails = EmailLog.query.filter(
        db.func.date(EmailLog.sent_at) == today
    ).order_by(EmailLog.sent_at.desc()).all()
    return render_template('today.html', activities=activities, emails=emails, today=today)


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
        school.priority_tier = request.form.get('priority_tier') or None
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
        school.last_contacted = datetime.utcnow()
        if request.form.get('stage'):
            school.stage = request.form['stage']
        if request.form.get('club_status'):
            school.after_school_club_status = request.form['club_status']
        if request.form.get('assembly_opportunity'):
            school.assembly_opportunity = request.form['assembly_opportunity']
        if 'won' in request.form:
            school.won = True
            school.stage = 'Won'
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
@delete_required
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

def add_working_days(start_date, days):
    """Return a date that is `days` working days after start_date, skipping weekends."""
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon–Fri
            added += 1
    return current


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

    # Stamp last_contacted on the school
    if message_id and school_id:
        school_obj = School.query.get(school_id)
        if school_obj:
            school_obj.last_contacted = datetime.utcnow()

    # Auto-create a follow-up activity 3 working days from today for school emails
    if message_id and school_id:
        followup_date = add_working_days(date.today(), 3)
        followup = Activity(
            school_id=school_id,
            user_id=current_user.id,
            type='call',
            outcome='',
            notes=f'Auto follow-up for email sent: {subject}',
            next_action=f'Follow up on email sent to {to_name or to_email}',
            follow_up_date=followup_date,
        )
        db.session.add(followup)

    db.session.commit()

    if error:
        flash(f'Failed to send: {error}', 'danger')
    else:
        if school_id:
            followup_date = add_working_days(date.today(), 3)
            flash(f'Email sent to {to_email}. Follow-up call scheduled for {followup_date.strftime("%A %d %b")}.', 'success')
        else:
            flash(f'Email sent to {to_email}.', 'success')

    if school_id:
        return redirect(url_for('school_detail', school_id=school_id))
    if parent_id:
        return redirect(url_for('parent_detail', parent_id=parent_id))
    return redirect(request.referrer)


# ── Messaging ─────────────────────────────────────────────────────────────────

@app.route('/messages')
@login_required
def messages_inbox():
    inbox = Message.query.filter_by(recipient_id=current_user.id) \
                   .order_by(Message.created_at.desc()).all()
    sent = Message.query.filter_by(sender_id=current_user.id) \
                  .order_by(Message.created_at.desc()).all()
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('messages/inbox.html', inbox=inbox, sent=sent, users=users)


@app.route('/messages/send', methods=['POST'])
@login_required
def message_send():
    recipient = User.query.get_or_404(request.form.get('recipient_id', type=int))
    msg = Message(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        subject=request.form.get('subject', '').strip(),
        body=request.form.get('body', '').strip(),
    )
    db.session.add(msg)
    db.session.commit()
    flash(f'Message sent to {recipient.name}.', 'success')
    return redirect(url_for('messages_inbox'))


@app.route('/messages/<int:msg_id>')
@login_required
def message_view(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.recipient_id != current_user.id and msg.sender_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('messages_inbox'))
    if msg.recipient_id == current_user.id and not msg.read:
        msg.read = True
        db.session.commit()
    return render_template('messages/view.html', msg=msg)


@app.route('/messages/<int:msg_id>/delete', methods=['POST'])
@login_required
def message_delete(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.recipient_id == current_user.id or msg.sender_id == current_user.id:
        db.session.delete(msg)
        db.session.commit()
    return redirect(url_for('messages_inbox'))


@app.route('/api/unread_count')
@login_required
def api_unread_count():
    count = Message.query.filter_by(recipient_id=current_user.id, read=False).count()
    return jsonify({'count': count})


# ── Calendar ──────────────────────────────────────────────────────────────────

@app.route('/calendar')
@login_required
def calendar_view():
    return render_template('calendar.html')


@app.route('/api/calendar/events')
@login_required
def calendar_events():
    events = []

    # School activities with a follow-up date
    activities = Activity.query.filter(Activity.follow_up_date != None).all()
    type_colors = {
        'call':    '#0d6efd',
        'meeting': '#6f42c1',
        'email':   '#0dcaf0',
        'note':    '#6c757d',
    }
    for a in activities:
        label = a.next_action or a.outcome or a.type.capitalize()
        school_name = a.school.name if a.school else ''
        events.append({
            'id': f'act-{a.id}',
            'title': f'{school_name} — {label}',
            'start': a.follow_up_date.isoformat(),
            'color': '#dc3545' if (not a.follow_up_complete and a.follow_up_date < date.today()) else type_colors.get(a.type, '#6c757d'),
            'url': url_for('school_detail', school_id=a.school_id),
            'extendedProps': {
                'type': a.type,
                'complete': a.follow_up_complete,
                'notes': a.notes or '',
            }
        })

    # Parent events (birthday parties, holiday camps etc.)
    parents = Parent.query.filter(Parent.event_date != None).all()
    parent_colors = {
        'Birthday Party': '#fd7e14',
        'Holiday Camp':   '#20c997',
        'Assembly':       '#6f42c1',
    }
    for p in parents:
        color = parent_colors.get(p.enquiry_type, '#fd7e14')
        events.append({
            'id': f'par-{p.id}',
            'title': f'🎂 {p.enquiry_type or "Event"} — {p.child_name or p.name}',
            'start': p.event_date.isoformat(),
            'color': color,
            'url': url_for('parent_detail', parent_id=p.id),
            'extendedProps': {'type': p.enquiry_type, 'notes': p.notes or ''}
        })

    # School assembly dates
    schools_with_assembly = School.query.filter(School.assembly_date != None).all()
    for s in schools_with_assembly:
        events.append({
            'id': f'asm-{s.id}',
            'title': f'🏫 Assembly — {s.name}',
            'start': s.assembly_date.isoformat(),
            'color': '#6f42c1',
            'url': url_for('school_detail', school_id=s.id),
            'extendedProps': {'type': 'Assembly', 'notes': ''}
        })

    return jsonify(events)


# ── Reminders API ─────────────────────────────────────────────────────────────

@app.route('/api/reminders')
@login_required
def api_reminders():
    today = date.today()
    overdue = Activity.query.filter(
        Activity.follow_up_date < today,
        Activity.follow_up_complete == False
    ).count()
    due_today = Activity.query.filter(
        Activity.follow_up_date == today,
        Activity.follow_up_complete == False
    ).count()
    return jsonify({'overdue': overdue, 'due_today': due_today})


# ── Pipeline (Kanban) ─────────────────────────────────────────────────────────

@app.route('/pipeline')
@login_required
def pipeline():
    stages = ['New', 'Contacted', 'Interested', 'Demo Booked', 'Won', 'Lost']
    board = {s: [] for s in stages}
    for school in School.query.order_by(School.name).all():
        s = school.stage or 'New'
        if s not in board:
            s = 'New'
        board[s].append(school)
    return render_template('pipeline.html', board=board, stages=stages)


@app.route('/pipeline/move', methods=['POST'])
@login_required
def pipeline_move():
    school = School.query.get_or_404(request.form.get('school_id', type=int))
    school.stage = request.form.get('stage')
    db.session.commit()
    return jsonify({'ok': True})


# ── Quick Note ────────────────────────────────────────────────────────────────

@app.route('/schools/<int:school_id>/note', methods=['POST'])
@login_required
def school_quick_note(school_id):
    school = School.query.get_or_404(school_id)
    note_text = request.form.get('note', '').strip()
    if note_text:
        school.school_notes = note_text
        db.session.commit()
    return redirect(url_for('school_detail', school_id=school_id))


# ── Bulk Email ────────────────────────────────────────────────────────────────

@app.route('/email/bulk', methods=['GET', 'POST'])
@login_required
@manager_required
def bulk_email():
    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    if request.method == 'POST':
        school_ids = request.form.getlist('school_ids')
        template_id = request.form.get('template_id', type=int)
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body_html', '').strip()
        template_name = request.form.get('template_name', '')

        sent, failed = 0, 0
        for sid in school_ids:
            school = School.query.get(int(sid))
            if not school or not school.main_email:
                failed += 1
                continue
            # Apply merge fields
            s = subject.replace('{{school_name}}', school.name or '') \
                       .replace('{{school_name | upper}}', (school.name or '').upper()) \
                       .replace('{{headteacher}}', school.headteacher or '') \
                       .replace('{{city}}', school.city or '')
            b = body.replace('{{school_name}}', school.name or '') \
                    .replace('{{school_name | upper}}', (school.name or '').upper()) \
                    .replace('{{headteacher}}', school.headteacher or '') \
                    .replace('{{city}}', school.city or '')
            msg_id, err = send_email(school.main_email, school.name, s, b)
            log = EmailLog(
                school_id=school.id,
                user_id=current_user.id,
                to_email=school.main_email,
                to_name=school.name,
                subject=s,
                body_html=b,
                template_name=template_name,
                status='sent' if msg_id else 'error',
                brevo_message_id=msg_id,
                error_message=err,
            )
            db.session.add(log)
            if msg_id:
                sent += 1
            else:
                failed += 1
        db.session.commit()
        flash(f'Bulk email complete: {sent} sent, {failed} failed.', 'success' if not failed else 'warning')
        return redirect(url_for('bulk_email'))

    # GET — show school selector
    tier = request.args.get('tier', '')
    stage = request.args.get('stage', '')
    schools_q = School.query.order_by(School.name)
    if tier:
        schools_q = schools_q.filter(School.priority_tier == tier)
    if stage:
        schools_q = schools_q.filter(School.stage == stage)
    schools_list = schools_q.all()
    stages = ['New', 'Contacted', 'Interested', 'Demo Booked', 'Won', 'Lost']
    return render_template('email/bulk.html', schools=schools_list, templates=templates,
                           tier=tier, stage=stage, stages=stages)


# ── Reports ───────────────────────────────────────────────────────────────────

@app.route('/reports')
@login_required
def reports():
    today = date.today()

    # Calls today per user
    calls_today = db.session.query(
        User.name, func.count(Activity.id)
    ).join(Activity, Activity.user_id == User.id) \
     .filter(Activity.type == 'call', func.date(Activity.created_at) == today) \
     .group_by(User.name).all()

    # Activity last 7 days
    from datetime import timedelta
    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = Activity.query.filter(
            Activity.type == 'call',
            func.date(Activity.created_at) == d
        ).count()
        days.append({'date': d.strftime('%a %d %b'), 'count': count})

    # Outcome breakdown
    outcomes = db.session.query(
        Activity.outcome, func.count(Activity.id)
    ).filter(Activity.type == 'call', Activity.outcome != '') \
     .group_by(Activity.outcome).order_by(func.count(Activity.id).desc()).all()

    # Pipeline stage counts
    stages = ['New', 'Contacted', 'Interested', 'Demo Booked', 'Won', 'Lost']
    stage_counts = {}
    for s in stages:
        stage_counts[s] = School.query.filter(School.stage == s).count()

    # Email stats
    email_stats = db.session.query(
        EmailLog.status, func.count(EmailLog.id)
    ).group_by(EmailLog.status).all()

    # Per-user activity this week
    week_start = today - timedelta(days=today.weekday())
    user_activity = db.session.query(
        User.name,
        func.count(Activity.id).label('total'),
        func.sum(db.case((Activity.type == 'call', 1), else_=0)).label('calls'),
        func.sum(db.case((Activity.type == 'email', 1), else_=0)).label('emails'),
    ).join(Activity, Activity.user_id == User.id) \
     .filter(func.date(Activity.created_at) >= week_start) \
     .group_by(User.name).all()

    # Tier breakdown
    tier_counts = sorted([
        (tier, count) for tier, count in
        db.session.query(School.priority_tier, func.count(School.id)).group_by(School.priority_tier).all()
        if tier is not None
    ], key=lambda x: x[0])

    return render_template('reports.html',
        calls_today=calls_today, days=days, outcomes=outcomes,
        stage_counts=stage_counts, email_stats=email_stats,
        user_activity=user_activity, tier_counts=tier_counts, today=today)


@app.route('/email/templates', methods=['GET', 'POST'])
@login_required
@manager_required
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
@delete_required
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


# ── Bookings ──────────────────────────────────────────────────────────────────

BOOKING_TYPES = ['Birthday Party', 'Workshop (Half Day)', 'Workshop (Full Day)', 'After School Club', 'Holiday Camp', 'Assembly', 'Other']
BOOKING_STATUSES = ['Enquiry', 'Confirmed', 'Invoiced', 'Paid', 'Cancelled']

@app.route('/bookings')
@login_required
def bookings():
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')
    q = Booking.query
    if status_filter:
        q = q.filter(Booking.status == status_filter)
    if type_filter:
        q = q.filter(Booking.booking_type == type_filter)
    all_bookings = q.order_by(Booking.event_date.desc()).all()
    total_revenue = sum(b.total_revenue for b in all_bookings if b.status != 'Cancelled')
    total_paid = sum((b.amount_paid or 0) for b in all_bookings if b.status != 'Cancelled')
    total_outstanding = total_revenue - total_paid
    return render_template('bookings/index.html',
        bookings=all_bookings,
        booking_types=BOOKING_TYPES,
        booking_statuses=BOOKING_STATUSES,
        status_filter=status_filter,
        type_filter=type_filter,
        total_revenue=total_revenue,
        total_paid=total_paid,
        total_outstanding=total_outstanding,
    )

@app.route('/bookings/new', methods=['GET', 'POST'])
@login_required
def booking_new():
    schools = School.query.order_by(School.name).all()
    if request.method == 'POST':
        school_id = request.form.get('school_id', type=int) or None
        num_children = request.form.get('num_children', type=int)
        num_weeks = request.form.get('num_weeks', type=int)
        price_per_child = request.form.get('price_per_child', type=float)
        flat_fee = request.form.get('flat_fee', type=float)
        event_date_str = request.form.get('event_date')
        end_date_str = request.form.get('end_date')
        b = Booking(
            school_id=school_id,
            user_id=current_user.id,
            booking_type=request.form.get('booking_type'),
            title=request.form.get('title', '').strip(),
            client_name=request.form.get('client_name', '').strip(),
            client_email=request.form.get('client_email', '').strip(),
            client_phone=request.form.get('client_phone', '').strip(),
            event_date=datetime.strptime(event_date_str, '%Y-%m-%d').date() if event_date_str else None,
            end_date=datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None,
            num_children=num_children,
            num_weeks=num_weeks,
            price_per_child=price_per_child,
            flat_fee=flat_fee,
            notes=request.form.get('notes', '').strip(),
            status=request.form.get('status', 'Enquiry'),
        )
        db.session.add(b)
        db.session.commit()
        flash('Booking created.', 'success')
        return redirect(url_for('booking_detail', booking_id=b.id))
    return render_template('bookings/new.html', schools=schools, booking_types=BOOKING_TYPES, booking_statuses=BOOKING_STATUSES)

@app.route('/bookings/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    b = Booking.query.get_or_404(booking_id)
    return render_template('bookings/detail.html', booking=b, booking_types=BOOKING_TYPES, booking_statuses=BOOKING_STATUSES)

@app.route('/bookings/<int:booking_id>/edit', methods=['GET', 'POST'])
@login_required
def booking_edit(booking_id):
    b = Booking.query.get_or_404(booking_id)
    schools = School.query.order_by(School.name).all()
    if request.method == 'POST':
        b.school_id = request.form.get('school_id', type=int) or None
        b.booking_type = request.form.get('booking_type')
        b.title = request.form.get('title', '').strip()
        b.client_name = request.form.get('client_name', '').strip()
        b.client_email = request.form.get('client_email', '').strip()
        b.client_phone = request.form.get('client_phone', '').strip()
        event_date_str = request.form.get('event_date')
        end_date_str = request.form.get('end_date')
        b.event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date() if event_date_str else None
        b.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        b.num_children = request.form.get('num_children', type=int)
        b.num_weeks = request.form.get('num_weeks', type=int)
        b.price_per_child = request.form.get('price_per_child', type=float)
        b.flat_fee = request.form.get('flat_fee', type=float)
        b.notes = request.form.get('notes', '').strip()
        b.status = request.form.get('status', b.status)
        amount_paid = request.form.get('amount_paid', type=float)
        if amount_paid is not None:
            b.amount_paid = amount_paid
            if amount_paid >= b.total_revenue and b.status != 'Paid':
                b.status = 'Paid'
                b.paid_at = datetime.utcnow()
        db.session.commit()
        flash('Booking updated.', 'success')
        return redirect(url_for('booking_detail', booking_id=b.id))
    return render_template('bookings/edit.html', booking=b, schools=schools, booking_types=BOOKING_TYPES, booking_statuses=BOOKING_STATUSES)

@app.route('/bookings/<int:booking_id>/delete', methods=['POST'])
@login_required
def booking_delete(booking_id):
    b = Booking.query.get_or_404(booking_id)
    db.session.delete(b)
    db.session.commit()
    flash('Booking deleted.', 'success')
    return redirect(url_for('bookings'))


# ── Invoices ──────────────────────────────────────────────────────────────────

def generate_invoice_number(booking_id):
    return f'INV-{datetime.utcnow().year}-{booking_id:04d}'

def build_invoice_pdf(booking):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=15*mm, bottomMargin=20*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    W = A4[0] - 40*mm

    brand_green = colors.HexColor('#198754')
    light_grey  = colors.HexColor('#f8f9fa')
    mid_grey    = colors.HexColor('#6c757d')

    h1 = ParagraphStyle('h1', fontSize=22, fontName='Helvetica-Bold', textColor=brand_green, spaceAfter=2)
    h2 = ParagraphStyle('h2', fontSize=11, fontName='Helvetica-Bold', spaceAfter=4)
    normal = ParagraphStyle('normal', fontSize=9, fontName='Helvetica', leading=13)
    small  = ParagraphStyle('small', fontSize=8, fontName='Helvetica', textColor=mid_grey, leading=12)
    right  = ParagraphStyle('right', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT)
    bold_right = ParagraphStyle('bold_right', fontSize=11, fontName='Helvetica-Bold', alignment=TA_RIGHT)

    story = []

    # Header: company left, INVOICE right
    header_data = [
        [Paragraph('<b>Inventors League Limited</b>', h2),
         Paragraph('INVOICE', ParagraphStyle('inv', fontSize=28, fontName='Helvetica-Bold',
                                              textColor=brand_green, alignment=TA_RIGHT))],
        [Paragraph('hello@inventorsleague.co.uk', small),
         Paragraph(f'Invoice No: <b>{booking.invoice_number}</b>', right)],
        [Paragraph('inventorsleague.co.uk', small),
         Paragraph(f'Date: <b>{datetime.utcnow().strftime("%d %B %Y")}</b>', right)],
        [Paragraph('', small),
         Paragraph(f'Due: <b>{datetime.utcnow().strftime("%d %B %Y")}</b>', right)],
    ]
    header_table = Table(header_data, colWidths=[W*0.55, W*0.45])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width=W, thickness=2, color=brand_green))
    story.append(Spacer(1, 6*mm))

    # Bill to
    bill_name = booking.school.name if booking.school else (booking.client_name or 'Customer')
    bill_email = (booking.school.main_email if booking.school else booking.client_email) or ''
    story.append(Paragraph('BILL TO', ParagraphStyle('label', fontSize=8, fontName='Helvetica-Bold',
                                                      textColor=mid_grey, spaceAfter=2)))
    story.append(Paragraph(f'<b>{bill_name}</b>', normal))
    if bill_email:
        story.append(Paragraph(bill_email, small))
    story.append(Spacer(1, 6*mm))

    # Line items table
    if booking.booking_type == 'After School Club':
        desc = (f'{booking.booking_type} — {booking.title}<br/>'
                f'{booking.num_children or 0} children × {booking.num_weeks or 0} weeks')
        unit_price = booking.price_per_child or 0
        qty = (booking.num_children or 0) * (booking.num_weeks or 0)
    elif booking.flat_fee:
        desc = f'{booking.booking_type} — {booking.title}'
        unit_price = booking.flat_fee
        qty = 1
    else:
        desc = f'{booking.booking_type} — {booking.title}'
        unit_price = booking.price_per_child or 0
        qty = booking.num_children or 1

    if booking.event_date:
        desc += f'<br/>Date: {booking.event_date.strftime("%d %B %Y")}'

    total = booking.total_revenue

    items_data = [
        [Paragraph('<b>Description</b>', normal), Paragraph('<b>Qty</b>', right),
         Paragraph('<b>Unit Price</b>', right), Paragraph('<b>Amount</b>', right)],
        [Paragraph(desc, normal), Paragraph(str(qty), right),
         Paragraph(f'£{unit_price:,.2f}', right), Paragraph(f'£{total:,.2f}', right)],
    ]
    col_widths = [W*0.55, W*0.1, W*0.17, W*0.18]
    items_table = Table(items_data, colWidths=col_widths)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_green),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [light_grey, colors.white]),
        ('GRID', (0,0), (-1,-1), 0.25, colors.HexColor('#dee2e6')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4*mm))

    # Totals block (right-aligned)
    totals_data = [
        ['', 'Subtotal', f'£{total:,.2f}'],
        ['', 'VAT (0%)', '£0.00'],
        ['', Paragraph('<b>TOTAL DUE</b>', bold_right), Paragraph(f'<b>£{total:,.2f}</b>', bold_right)],
    ]
    totals_table = Table(totals_data, colWidths=[W*0.55, W*0.25, W*0.20])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('LINEABOVE', (1,2), (-1,2), 1, brand_green),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 10*mm))

    # Payment details
    story.append(HRFlowable(width=W, thickness=0.5, color=colors.HexColor('#dee2e6')))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph('<b>Payment Details</b>', h2))
    story.append(Paragraph('Please make payment by BACS transfer to:', normal))
    story.append(Spacer(1, 2*mm))
    bank_data = [
        ['Account Name:', 'Inventors League Limited'],
        ['Sort Code:', os.environ.get('BANK_SORT_CODE', '00-00-00')],
        ['Account Number:', os.environ.get('BANK_ACCOUNT_NUMBER', '00000000')],
        ['Reference:', booking.invoice_number],
    ]
    bank_table = Table(bank_data, colWidths=[W*0.25, W*0.75])
    bank_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(bank_table)

    if booking.notes:
        story.append(Spacer(1, 6*mm))
        story.append(Paragraph('<b>Notes</b>', h2))
        story.append(Paragraph(booking.notes, normal))

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width=W, thickness=0.5, color=colors.HexColor('#dee2e6')))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph('Thank you for choosing Inventors League!',
                            ParagraphStyle('footer', fontSize=8, textColor=mid_grey, alignment=TA_CENTER)))

    doc.build(story)
    buf.seek(0)
    return buf


@app.route('/bookings/<int:booking_id>/invoice/pdf')
@login_required
def booking_invoice_pdf(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if not b.invoice_number:
        b.invoice_number = generate_invoice_number(b.id)
        if b.status == 'Confirmed':
            b.status = 'Invoiced'
            b.invoice_sent_at = datetime.utcnow()
        db.session.commit()
    pdf = build_invoice_pdf(b)
    filename = f'Invoice-{b.invoice_number}.pdf'
    return send_file(pdf, mimetype='application/pdf',
                     as_attachment=request.args.get('download') == '1',
                     download_name=filename)


@app.route('/bookings/<int:booking_id>/invoice/send', methods=['POST'])
@login_required
def booking_invoice_send(booking_id):
    b = Booking.query.get_or_404(booking_id)
    to_email = request.form.get('invoice_email', '').strip()
    to_name = request.form.get('invoice_name', '').strip()

    if not to_email:
        flash('Please enter an email address to send the invoice to.', 'danger')
        return redirect(url_for('booking_detail', booking_id=b.id))

    if not b.invoice_number:
        b.invoice_number = generate_invoice_number(b.id)

    pdf = build_invoice_pdf(b)
    pdf_bytes = pdf.read()

    # Send via Brevo SMTP with attachment
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    smtp_user = os.environ.get('BREVO_SMTP_USER')
    smtp_pass = os.environ.get('BREVO_SMTP_PASS')
    sender_email = os.environ.get('BREVO_SENDER_EMAIL', 'hello@inventorsleague.co.uk')
    sender_name  = os.environ.get('BREVO_SENDER_NAME', 'Inventors League')

    subject = f'Invoice {b.invoice_number} — {b.title}'
    body_html = f"""
    <p>Dear {to_name or 'there'},</p>
    <p>Please find attached your invoice <strong>{b.invoice_number}</strong> for <strong>{b.title}</strong>.</p>
    <p>Total due: <strong>£{b.total_revenue:,.2f}</strong></p>
    <p>Please make payment by BACS using the details on the invoice, quoting reference <strong>{b.invoice_number}</strong>.</p>
    <p>If you have any questions, please don't hesitate to get in touch.</p>
    <p>Many thanks,<br>The Inventors League Team</p>
    """

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = f'{sender_name} <{sender_email}>'
    msg['To'] = f'{to_name} <{to_email}>' if to_name else to_email
    msg.attach(MIMEText(body_html, 'html'))

    attachment = MIMEBase('application', 'pdf')
    attachment.set_payload(pdf_bytes)
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', f'attachment; filename="Invoice-{b.invoice_number}.pdf"')
    msg.attach(attachment)

    try:
        with smtplib.SMTP('smtp-relay.brevo.com', 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender_email, to_email, msg.as_string())
        b.status = 'Invoiced'
        b.invoice_sent_at = datetime.utcnow()
        db.session.commit()
        flash(f'Invoice {b.invoice_number} sent to {to_email}.', 'success')
    except Exception as e:
        flash(f'Failed to send invoice: {e}', 'danger')

    return redirect(url_for('booking_detail', booking_id=b.id))


# ── Data Import ───────────────────────────────────────────────────────────────

@app.route('/admin/import', methods=['GET', 'POST'])
@login_required
@admin_required
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
@admin_required
def admin_users():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            existing = User.query.filter_by(email=request.form['email'].strip().lower()).first()
            if existing:
                flash('Email already exists.', 'danger')
            else:
                user = User(
                    name=request.form['name'],
                    email=request.form['email'].strip().lower(),
                    role=request.form.get('role', 'user'),
                )
                user.set_password(request.form['password'])
                db.session.add(user)
                db.session.commit()
                flash(f'User {user.name} created.', 'success')
        elif action == 'update_role':
            user = User.query.get_or_404(request.form.get('user_id', type=int))
            if user.id == current_user.id:
                flash('You cannot change your own role.', 'danger')
            else:
                user.role = request.form.get('role', 'user')
                db.session.commit()
                flash(f'{user.name} role updated to {user.role}.', 'success')
        elif action == 'delete':
            user = User.query.get_or_404(request.form.get('user_id', type=int))
            if user.id == current_user.id:
                flash('You cannot delete yourself.', 'danger')
            else:
                db.session.delete(user)
                db.session.commit()
                flash(f'User deleted.', 'success')
        elif action == 'reset_password':
            user = User.query.get_or_404(request.form.get('user_id', type=int))
            user.set_password(request.form.get('new_password'))
            db.session.commit()
            flash(f'Password reset for {user.name}.', 'success')
        return redirect(url_for('admin_users'))
    users = User.query.order_by(User.name).all()
    return render_template('auth/users.html', users=users)


# ── Init ──────────────────────────────────────────────────────────────────────

def migrate_db():
    """Add any missing columns without dropping data."""
    migrations = [
        ('schools', 'business_manager_name',  'VARCHAR(200)'),
        ('schools', 'business_manager_email', 'VARCHAR(150)'),
        ('schools', 'stage',                  "VARCHAR(50) DEFAULT 'New'"),
        ('schools', 'school_notes',           'TEXT'),
        ('users',   'last_seen',              'TIMESTAMP'),
        ('users',   'role',                   "VARCHAR(20) DEFAULT 'user'"),
        ('schools', 'last_contacted',         'TIMESTAMP'),
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
