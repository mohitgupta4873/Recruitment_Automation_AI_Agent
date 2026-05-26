"""
campaign_manager.py
Multi-campaign support layer.

Storage layout (all under BASE_DIR/campaigns/):
  campaigns/
    user_{user_id}/
      _index.json            <- lightweight list of all campaigns
      campaign_{id}.json     <- full HiringAutomator state for that campaign

The _index.json looks like:
  [
    {
      "id": "abc123",
      "role": "Backend Engineer",
      "status": "active",        # active | completed | paused
      "created_at": "2026-05-26T10:00:00",
      "candidates_count": 5,
      "form_url": "https://...",
      "sheet_url": "https://..."
    },
    ...
  ]
"""

import os
import json
import uuid
from datetime import datetime
from django.conf import settings


# ── Path helpers ─────────────────────────────────────────────

def _user_dir(user_id):
    d = os.path.join(settings.BASE_DIR, 'campaigns', f'user_{user_id}')
    os.makedirs(d, exist_ok=True)
    return d


def _index_path(user_id):
    return os.path.join(_user_dir(user_id), '_index.json')


def campaign_state_path(user_id, campaign_id):
    return os.path.join(_user_dir(user_id), f'campaign_{campaign_id}.json')


# ── Index CRUD ───────────────────────────────────────────────

def load_index(user_id):
    path = _index_path(user_id)
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding='utf-8'))
        except Exception:
            return []
    return []


def save_index(user_id, index):
    path = _index_path(user_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2)


def get_campaign_meta(user_id, campaign_id):
    """Return the lightweight index entry for a specific campaign."""
    return next((c for c in load_index(user_id) if c['id'] == campaign_id), None)


def upsert_campaign_meta(user_id, campaign_id, **kwargs):
    """Create or update a campaign's index entry."""
    index = load_index(user_id)
    existing = next((c for c in index if c['id'] == campaign_id), None)
    if existing:
        existing.update(kwargs)
    else:
        entry = {'id': campaign_id, 'created_at': datetime.now().isoformat(), **kwargs}
        index.insert(0, entry)   # newest first
    save_index(user_id, index)


def sync_index_from_state(user_id, campaign_id):
    """
    After a campaign's state file is written, keep the index in sync
    (candidates count, role, urls, status).
    """
    state_path = campaign_state_path(user_id, campaign_id)
    if not os.path.exists(state_path):
        return
    try:
        state = json.load(open(state_path, encoding='utf-8'))
    except Exception:
        return

    upsert_campaign_meta(
        user_id, campaign_id,
        role=state.get('role', 'Unnamed'),
        candidates_count=len(state.get('candidates', [])),
        form_url=state.get('form_url', ''),
        sheet_url=state.get('sheet_url', ''),
        status=state.get('status', 'active'),
    )


# ── Session helpers ───────────────────────────────────────────

SESSION_KEY = 'active_campaign_id'


def get_active_campaign_id(request):
    return request.session.get(SESSION_KEY)


def set_active_campaign_id(request, campaign_id):
    request.session[SESSION_KEY] = campaign_id
    request.session.modified = True


def clear_active_campaign(request):
    request.session.pop(SESSION_KEY, None)
    request.session.modified = True


# ── High-level helpers ────────────────────────────────────────

def create_new_campaign(request):
    """
    Generate a new campaign ID, set it active in the session, and
    return (campaign_id, state_path).  Does NOT write state yet —
    that happens when the JD is generated / campaign is launched.
    """
    campaign_id = uuid.uuid4().hex[:12]
    set_active_campaign_id(request, campaign_id)
    user_id = request.user.id
    # Register in index immediately so it shows in history
    upsert_campaign_meta(
        user_id, campaign_id,
        role='New Campaign',
        status='draft',
        candidates_count=0,
        form_url='',
        sheet_url='',
    )
    return campaign_id, campaign_state_path(user_id, campaign_id)


def ensure_active_campaign(request):
    """
    If the user has no active campaign in session, auto-create one.
    Returns (campaign_id, state_path).
    """
    campaign_id = get_active_campaign_id(request)
    if not campaign_id:
        # Try to pick the most recent non-draft campaign from index
        index = load_index(request.user.id)
        non_draft = [c for c in index if c.get('status') != 'draft']
        if non_draft:
            campaign_id = non_draft[0]['id']
            set_active_campaign_id(request, campaign_id)
        else:
            return create_new_campaign(request)
    return campaign_id, campaign_state_path(request.user.id, campaign_id)
