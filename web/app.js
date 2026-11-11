'use strict';

const view = document.querySelector('#view');
const notice = document.querySelector('#notice');
let state;
let busy = false;

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const link = (text, href) => el('a', { href, text });
const member = id => state.members.find(record => record.id === id);
const event = id => state.events.find(record => record.id === id);
const appearances = (field, id) => state.engagements.filter(record => record[field] === id);
const confirmedCount = id => appearances('event_id', id).filter(record => record.status === 'confirmed').length;
const badge = status => el('span', { class: `badge ${status}`, text: status[0].toUpperCase() + status.slice(1) });
const utcDate = value => new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(value));
const utcTime = value => value.slice(11, 16);
const when = record => `${utcDate(record.start)} · ${utcTime(record.start)}–${utcTime(record.end)} UTC${record.start.slice(0, 10) !== record.end.slice(0, 10) ? ` (ends ${utcDate(record.end)})` : ''}`;

function showNotice(message, reasons = [], error = false) {
  notice.replaceChildren(el('strong', { text: message }));
  notice.className = `notice${error ? ' error' : ''}`;
  notice.setAttribute('role', error ? 'alert' : 'status');
  if (reasons.length) notice.append(reasonList(reasons));
  notice.hidden = false;
  notice.scrollIntoView({ behavior: 'instant', block: 'nearest' });
}
function reasonList(reasons) {
  return el('ul', {}, reasons.map(reason => el('li', {}, reason.message, ' ', link('View event', `#events/${reason.event_id}`))));
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, { ...options, credentials: 'same-origin' }); }
  catch (_) { throw new Error('Cannot reach the local server. Start it again, then refresh records.'); }
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || 'The request could not be completed.');
    error.reasons = data.reasons || [];
    throw error;
  }
  return data;
}
async function load() { state = await api('/api/state'); render(); }
async function update(table, record, values, message) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  let saved = false;
  try {
    await api(`/api/${table}/${record.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version: record.version, ...values }) });
    saved = true;
    await load();
    showNotice(message);
  } catch (error) {
    showNotice(saved ? 'Your change was saved, but records could not be refreshed. Use Refresh records before editing again.' : error.message, error.reasons || [], true);
  } finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => { button.disabled = button.dataset.current === 'true'; });
  }
}
function heading(title, subtitle) {
  return [el('h1', { text: title }), el('p', { class: 'subtitle', text: subtitle })];
}
function breadcrumbs(items) {
  return el('nav', { class: 'breadcrumbs', 'aria-label': 'Breadcrumb' }, items.map((item, index) => [index ? el('span', { 'aria-hidden': 'true', text: '/' }) : null, item.href ? link(item.text, item.href) : el('span', { text: item.text })]).flat());
}
function table(headers, rows) {
  return el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, headers.map(text => el('th', { scope: 'col', text })))), el('tbody', {}, rows)));
}
function eventList() {
  const query = el('input', { type: 'search', placeholder: 'Title, location or presenter', 'aria-label': 'Search events' });
  const filter = el('select', { 'aria-label': 'Filter events' }, el('option', { value: 'all', text: 'All events' }), el('option', { value: 'attention', text: 'Needs attention' }), el('option', { value: 'full', text: 'At presenter capacity' }));
  const results = el('div');
  function filterRows() {
    const search = query.value.trim().toLocaleLowerCase();
    const events = [...state.events].sort((a, b) => a.start.localeCompare(b.start)).filter(record => {
      const list = appearances('event_id', record.id);
      const haystack = [record.title, record.location, ...list.map(item => member(item.member_id).name)].join(' ').toLocaleLowerCase();
      return haystack.includes(search) && (filter.value === 'all' || (filter.value === 'full' ? confirmedCount(record.id) >= record.capacity : list.some(item => item.status === 'invited' && item.reasons.length)));
    });
    const rows = events.map(record => {
      const list = appearances('event_id', record.id);
      const attention = list.filter(item => item.status === 'invited' && item.reasons.length).length;
      return el('tr', {}, el('td', {}, link(record.title, `#events/${record.id}`), el('span', { class: 'secondary', text: record.location })), el('td', { class: 'numeric' }, utcDate(record.start), el('span', { class: 'secondary', text: `${utcTime(record.start)}–${utcTime(record.end)} UTC` })), el('td', {}, `${confirmedCount(record.id)} / ${record.capacity} confirmed`, el('span', { class: 'secondary', text: `${list.filter(item => item.status === 'invited').length} invited` })), el('td', {}, attention ? el('span', { class: 'attention', text: `${attention} invitation${attention === 1 ? '' : 's'} need attention` }) : el('span', { class: 'secondary', text: 'No invitation blockers' })));
    });
    results.replaceChildren(el('p', { class: 'count', text: `${events.length} event${events.length === 1 ? '' : 's'} shown` }), rows.length ? table(['Event', 'Schedule', 'Presenter slots', 'Invitation check'], rows) : el('p', { class: 'empty', text: 'No events match. Clear the search or choose All events.' }));
  }
  query.addEventListener('input', filterRows);
  filter.addEventListener('change', filterRows);
  view.append(...heading('A program built together.', 'Follow the people behind each event. Review invitations, resolve overlaps and keep the practical details in one place.'), el('div', { class: 'toolbar' }, el('label', {}, 'Search events', query), el('label', {}, 'Show', filter)), results);
  filterRows();
}
function memberList() {
  const query = el('input', { type: 'search', placeholder: 'Alias or specialty', 'aria-label': 'Search members' });
  const results = el('div');
  function filterRows() {
    const records = state.members.filter(record => `${record.name} ${record.specialty} ${record.bio}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()));
    results.replaceChildren(el('p', { class: 'count', text: `${records.length} members shown` }), records.length ? table(['Member alias', 'Practice', 'Commitments'], records.map(record => {
      const list = appearances('member_id', record.id);
      return el('tr', {}, el('td', {}, link(record.name, `#members/${record.id}`)), el('td', { text: record.specialty }), el('td', {}, `${list.filter(item => item.status === 'confirmed').length} confirmed`, el('span', { class: 'secondary', text: `${list.length} linked appearances` })));
    })) : el('p', { class: 'empty', text: 'No members match. Try another alias or specialty.' }));
  }
  query.addEventListener('input', filterRows);
  view.append(...heading('The people in the program.', 'Every alias is fictional. Open a profile to see invitations, confirmed appearances and a linked schedule.'), el('div', { class: 'toolbar' }, el('label', {}, 'Search members', query)), results);
  filterRows();
}
function field(label, name, value, type = 'text', options = {}) {
  const control = type === 'textarea' ? el('textarea', { name, maxlength: '2000' }) : el('input', { name, type, ...(type === 'text' ? { maxlength: '100' } : {}) });
  control.value = value;
  for (const [key, val] of Object.entries(options)) control.setAttribute(key, val);
  return el('label', { class: type === 'textarea' ? 'wide' : '' }, label, control);
}
function recordForm(tableName, record, fields) {
  const form = el('form', { class: 'form-grid' }, fields, el('div', { class: 'wide' }, el('button', { type: 'submit', text: tableName === 'members' ? 'Save profile' : 'Save event' }), el('p', { class: 'support', text: 'Changes are saved locally. Existing appearance logistics stay attached.' })));
  form.addEventListener('submit', eventObject => {
    eventObject.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    if (tableName === 'events') {
      values.capacity = Number(values.capacity);
      values.start += 'Z';
      values.end += 'Z';
    }
    update(tableName, record, values, tableName === 'members' ? 'Profile saved.' : 'Event saved. Confirmed presenter schedules checked.');
  });
  return form;
}
function appearanceRow(item, context) {
  const person = member(item.member_id);
  const program = event(item.event_id);
  return el('article', { class: 'appearance' }, el('div', { class: 'appearance-head' }, el('div', {}, link(context === 'event' ? person.name : program.title, context === 'event' ? `#members/${person.id}` : `#events/${program.id}`), el('span', { class: 'secondary', text: context === 'event' ? person.specialty : when(program) })), badge(item.status)), el('p', { text: item.notes || 'No appearance logistics recorded yet.' }), item.status === 'invited' && item.reasons.length ? el('span', { class: 'attention', text: `${item.reasons.length} confirmation blocker${item.reasons.length === 1 ? '' : 's'} to review` }) : null, el('div', { class: 'actions' }, link('Review appearance', `#engagements/${item.id}`)));
}
function eventDetail(record) {
  const list = appearances('event_id', record.id);
  view.append(breadcrumbs([{ text: 'Events', href: '#events' }, { text: record.title }]), ...heading(record.title, `${when(record)} · ${record.location}`));
  const left = el('section', {}, el('h2', { text: `People & appearances · ${confirmedCount(record.id)} / ${record.capacity} confirmed` }), list.map(item => appearanceRow(item, 'event')));
  const right = el('section', { class: 'panel' }, el('h2', { text: 'Event details' }), recordForm('events', record, [field('Event title', 'title', record.title, 'text', { required: '' }), field('Location', 'location', record.location, 'text', { required: '' }), field('Starts (UTC)', 'start', record.start.slice(0, -1), 'datetime-local', { required: '' }), field('Ends (UTC)', 'end', record.end.slice(0, -1), 'datetime-local', { required: '' }), field('Presenter capacity', 'capacity', record.capacity, 'number', { min: '1', max: '100', required: '' }), field('Event logistics', 'notes', record.notes, 'textarea')]));
  view.append(el('div', { class: 'columns' }, left, right));
}
function memberDetail(record) {
  const list = appearances('member_id', record.id).sort((a, b) => event(a.event_id).start.localeCompare(event(b.event_id).start));
  view.append(breadcrumbs([{ text: 'Members', href: '#members' }, { text: record.name }]), ...heading(record.name, record.specialty));
  const left = el('section', {}, el('p', { text: record.bio }), el('h2', { text: 'Appearance timeline' }), list.length ? list.map(item => el('div', { class: 'schedule-line' }, el('time', { datetime: event(item.event_id).start }, utcDate(event(item.event_id).start), el('br'), `${utcTime(event(item.event_id).start)} UTC`), el('div', {}, link(event(item.event_id).title, `#events/${item.event_id}`), ' ', badge(item.status), el('p', { text: item.notes }), el('div', { class: 'actions' }, link('Review appearance', `#engagements/${item.id}`))))) : el('p', { class: 'empty', text: 'This member has no linked appearances.' }));
  const right = el('section', { class: 'panel' }, el('h2', { text: 'Member profile' }), recordForm('members', record, [field('Member alias', 'name', record.name, 'text', { required: '' }), field('Specialty', 'specialty', record.specialty, 'text', { required: '' }), field('About this member', 'bio', record.bio, 'textarea')]));
  view.append(el('div', { class: 'columns' }, left, right));
}
function engagementDetail(record) {
  const person = member(record.member_id);
  const program = event(record.event_id);
  view.append(breadcrumbs([{ text: 'Events', href: '#events' }, { text: program.title, href: `#events/${program.id}` }, { text: person.name }]), ...heading(`${person.name} at ${program.title}`, 'One appearance record connects a person, a commitment and the details that make it happen.'));
  const summary = el('section', {}, el('h2', { text: 'Appearance' }), badge(record.status), el('p', {}, link(person.name, `#members/${person.id}`), ` · ${person.specialty}`), el('p', {}, link(program.title, `#events/${program.id}`), el('br'), when(program), el('br'), program.location), el('p', { text: `${confirmedCount(program.id)} of ${program.capacity} presenter slots confirmed.` }));
  if (record.reasons.length) summary.append(el('div', { class: 'blockers' }, el('strong', { text: 'Before this appearance can be confirmed' }), reasonList(record.reasons)));
  else summary.append(el('p', { class: 'support', text: record.status === 'confirmed' ? 'This commitment is included in schedule and capacity checks.' : 'No current blockers. Availability is checked again when you confirm.' }));
  summary.append(el('div', { class: 'actions' }, ['confirmed', 'declined', 'invited'].map(status => {
    const current = status === record.status;
    const button = el('button', { type: 'button', class: status === 'declined' ? 'decline' : status === 'invited' ? 'quiet' : '', 'data-current': String(current), text: status === 'confirmed' ? 'Confirm appearance' : status === 'declined' ? 'Decline appearance' : 'Return to invited', onclick: () => update('engagements', record, { status }, `Appearance ${status === 'invited' ? 'returned to invited' : status}.`) });
    button.disabled = current;
    return button;
  })));
  const notes = field('Appearance logistics', 'notes', record.notes, 'textarea');
  const form = el('form', {}, notes, el('div', { class: 'actions' }, el('button', { type: 'submit', text: 'Save logistics' })), el('p', { class: 'support', text: 'These notes belong to this appearance. Profile and event edits preserve them.' }));
  form.addEventListener('submit', eventObject => { eventObject.preventDefault(); update('engagements', record, { notes: new FormData(form).get('notes') }, 'Appearance logistics saved.'); });
  view.append(el('div', { class: 'columns' }, summary, el('section', { class: 'panel' }, el('h2', { text: 'Make it happen' }), form)));
}
function historyList() {
  view.append(...heading('What changed.', 'Successful edits appear here, newest first. Rejected changes leave records untouched. The most recent 100 changes are shown.'));
  if (!state.history.length) { view.append(el('p', { class: 'empty', text: 'No changes yet. Edit a profile or review an appearance to begin the local history.' })); return; }
  view.append(el('ol', { class: 'timeline' }, state.history.map(item => el('li', {}, el('time', { datetime: item.at, text: `${utcDate(item.at)} ${utcTime(item.at)} UTC` }), el('div', {}, item.message, ' ', link('Open record', `#${item.entity}/${item.entity_id}`))))));
}
function render() {
  if (!state) return;
  view.replaceChildren();
  const route = location.hash.slice(1) || 'events';
  const match = /^(events|members|engagements)(?:\/([1-9]\d*))?$/.exec(route);
  const section = route === 'timeline' ? 'timeline' : match ? (match[1] === 'engagements' ? 'events' : match[1]) : '';
  document.querySelectorAll('[data-nav]').forEach(node => { if (node.dataset.nav === section) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
  if (route === 'timeline') historyList();
  else if (match && !match[2] && match[1] !== 'engagements') (match[1] === 'events' ? eventList : memberList)();
  else if (match && match[2]) {
    const record = state[match[1]].find(item => item.id === Number(match[2]));
    if (record) ({ events: eventDetail, members: memberDetail, engagements: engagementDetail })[match[1]](record);
    else missing();
  } else missing();
  document.title = `${view.querySelector('h1')?.textContent || 'Records'} · Community Events Hub`;
}
function missing() { view.append(...heading('Record not found.', 'This link does not match a record in the local demo.'), link('Return to events', '#events')); }
document.querySelector('.skip').addEventListener('click', eventObject => {
  eventObject.preventDefault();
  document.querySelector('#content').focus();
});
window.addEventListener('hashchange', () => { notice.hidden = true; render(); document.querySelector('#content').focus({ preventScroll: true }); });
document.querySelector('#refresh').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  const button = document.querySelector('#refresh');
  button.disabled = true;
  try { await load(); showNotice('Records refreshed. The latest saved values are now shown.'); }
  catch (error) { showNotice(error.message, [], true); }
  finally { busy = false; button.disabled = false; }
});
load().catch(error => { view.replaceChildren(...heading('The program could not load.', 'Use Refresh records after the local server is running.')); showNotice(error.message, [], true); });
