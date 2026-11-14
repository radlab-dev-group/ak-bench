// AK-Bench Administration: deletion behind a confirmation that names the cost
// and makes the caller retype it. The custom header on every delete is the
// CSRF half of the gate (ADMIN_HEADER in bench_ui/security.py): a form on
// another site cannot set it and a fetch from another origin cannot add it
// without a CORS preflight this app never grants.
(() => {
  const ADMIN_HEADER = 'X-Akbench-Admin';

  // The dialog is drawn with the page's own panel language instead of the
  // browser's confirm box: same card, same buttons, same voice — and it will
  // not proceed until the caller types the exact name of what dies.
  function openConfirm({ kind, uid, warning, onConfirm }) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';

    const card = document.createElement('div');
    card.className = 'panel confirm-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');

    const header = document.createElement('div');
    header.className = 'panel-header';
    const title = document.createElement('div');
    title.className = 'panel-title';
    title.append('Delete ' + kind + ' ');
    const titleUid = document.createElement('span');
    titleUid.className = 'mono confirm-uid';
    titleUid.textContent = uid;
    title.append(titleUid, '?');
    header.append(title);

    const body = document.createElement('div');
    body.className = 'panel-body';

    const warn = document.createElement('div');
    warn.className = 'confirm-warning';
    warn.textContent = (warning ? warning + ' ' : '') + 'This cannot be undone.';

    const label = document.createElement('label');
    label.className = 'confirm-label';
    label.append('Type ');
    const labelUid = document.createElement('span');
    labelUid.className = 'mono confirm-uid';
    labelUid.textContent = uid;
    label.append(labelUid, ' to confirm');
    const input = document.createElement('input');
    input.className = 'input confirm-input';
    input.spellcheck = false;
    input.autocomplete = 'off';
    label.append(input);

    const actions = document.createElement('div');
    actions.className = 'confirm-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn btn-sm confirm-cancel';
    cancel.textContent = 'Cancel';
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'btn btn-sm btn-danger confirm-btn';
    confirm.textContent = 'Delete ' + kind;
    confirm.disabled = true;
    actions.append(cancel, confirm);

    body.append(warn, label, actions);
    card.append(header, body);
    overlay.append(card);

    const close = () => {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
    };
    const onKey = (event) => {
      if (event.key === 'Escape') close();
    };
    input.addEventListener('input', () => {
      confirm.disabled = input.value !== uid;
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !confirm.disabled) confirm.click();
    });
    cancel.addEventListener('click', close);
    confirm.addEventListener('click', () => {
      close();
      onConfirm();
    });
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) close();
    });
    document.addEventListener('keydown', onKey);

    document.body.append(overlay);
    input.focus();
  }

  function removeRowAndNote(button, kind, uid) {
    const row = button.closest('tr');
    const panel = button.closest('.panel');
    if (row) row.remove();
    if (panel) {
      panel.querySelectorAll('.admin-notice').forEach((el) => el.remove());
      const notice = document.createElement('div');
      notice.className = 'admin-notice';
      notice.textContent = 'Deleted ' + kind + ' "' + uid + '".';
      const body = panel.querySelector('.panel-body');
      if (body) body.appendChild(notice);
      const badge = panel.querySelector('.panel-header .badge');
      const rows = panel.querySelectorAll('tbody tr').length;
      if (badge && /shown/.test(badge.textContent)) badge.textContent = `${rows} shown`;
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('.admin-delete');
    if (!button) return;
    const { endpoint, kind, uid, warning } = button.dataset;
    openConfirm({
      kind,
      uid,
      warning,
      onConfirm: () => {
        button.disabled = true;
        fetch(endpoint, { method: 'DELETE', headers: { [ADMIN_HEADER]: '1' } })
          .then((response) => {
            if (!response.ok) {
              return response.json().catch(() => ({})).then((body) => {
                throw new Error(body.detail || 'HTTP ' + response.status);
              });
            }
            return response.json();
          })
          .then(() => removeRowAndNote(button, kind, uid))
          .catch((error) => {
            button.disabled = false;
            window.alert('Delete failed: ' + error.message);
          });
      },
    });
  });
})();
