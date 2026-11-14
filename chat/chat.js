let userName = 'Pengguna';

async function loadUser() {
    try {
        const res = await fetch('/api/me');
        if (!res.ok) return;
        const data = await res.json();
        userName = data.user?.name || data.user?.email || userName;
    } catch (_) { }
    document.getElementById('user-name').textContent = userName;
    document.getElementById('avatar').textContent = userName.charAt(0).toUpperCase();
    document.getElementById('greet-name').textContent = userName.split(' ')[0];
}
loadUser();

// ---------- Data demo (ganti dengan respons Flask /chat) ----------
const SOURCES = {
    1: {
        title: 'UU No. 13/2003 tentang Ketenagakerjaan, Pasal 156', status: 'berlaku',
        date: 'Diperbarui dengan UU No. 6/2023', note: 'Mengatur hak pekerja atas uang pesangon dan uang penghargaan masa kerja.',
        excerpt: 'Ringkasan: besaran kompensasi PHK bergantung pada masa kerja dan alasan pemutusan hubungan kerja.'
    },
    2: {
        title: 'UU No. 13/2003, Pasal 161', status: 'diubah',
        date: 'Diubah dengan UU No. 6/2023', note: 'Mengatur surat peringatan bertahap sebelum PHK karena pelanggaran pekerja.',
        excerpt: 'Ringkasan: PHK karena pelanggaran umumnya didahului surat peringatan, kecuali pelanggaran berat tertentu.'
    },
    3: {
        title: 'PP No. 35/2021 tentang PKWT dan PHK', status: 'berlaku',
        date: 'Berlaku sejak 2021', note: 'Mengatur kontrak waktu tertentu (PKWT), termasuk batas durasi dan perpanjangan.',
        excerpt: 'Ringkasan: PKWT memiliki batas total durasi dan ketentuan perpanjangan yang harus dipenuhi.'
    }
};

const ANSWERS = {
    'Apa hak saya jika di-PHK tanpa pesangon?': {
        mode: 'Tanya hukum',
        paras: [
            { t: 'Pada prinsipnya, pekerja yang di-PHK berhak atas kompensasi sesuai ketentuan ketenagakerjaan. Besarannya bergantung pada masa kerja dan alasan PHK.', c: [1] },
            { t: 'Jika PHK dilakukan tanpa prosedur surat peringatan yang diwajibkan, hak atas kompensasi dapat dipersoalkan. Hal ini perlu dicek dengan alasan PHK dan dokumen pendukung.', c: [2] }
        ],
        src: [1, 2], conf: 72,
        facts: 'Hubungan kerja: karyawan tetap. Alasan PHK: belum diketahui.',
        assumptions: 'PHK dilakukan oleh pengusaha, bukan atas permintaan sendiri.',
        verify: 'Besaran kompensasi konkret dan keabsahan alasan PHK.',
        followups: ['Hitung perkiraan pesangon', 'Apa beda PHK dan pengunduran diri?', 'Cari putusan terkait']
    },
    'Berapa lama maksimal kontrak kerja PKWT?': {
        mode: 'Riset regulasi',
        paras: [
            { t: 'PKWT dibatasi durasinya dan tidak dapat dibuat tanpa batas waktu. Batas total dan aturan perpanjangan diatur dalam peraturan pelaksana tentang PKWT.', c: [3] }
        ],
        src: [3], conf: 68,
        facts: 'Jenis hubungan kerja: PKWT.',
        assumptions: 'Tidak ada perjanjian khusus yang menyimpang dari ketentuan umum.',
        verify: 'Jenis pekerjaan, dan apakah termasuk pengecualian tertentu.',
        followups: ['Syarat perpanjangan PKWT', 'Apa akibat jika PKWT melewati batas?']
    }
};

// ---------- State ----------
const MODE_LABEL = { tanya: 'Tanya hukum', riset: 'Riset regulasi', review: 'Review dokumen', draft: 'Buat dokumen', opini: 'Opini IRAC' };
const MODE_PH = {
    tanya: 'Tanyakan pertanyaan hukum Anda…',
    riset: 'Tulis topik atau nomor peraturan, misalnya "UU 13/2003"…',
    review: 'Tempel klausul atau tulis bagian yang ingin direview…',
    draft: 'Jelaskan dokumen yang ingin dibuat dan para pihaknya…',
    opini: 'Tulis fakta perkara dan pertanyaan hukumnya…'
};
let mode = 'tanya', depth = 'Standar', busy = false;

// ---------- Elements ----------
const welcome = document.getElementById('welcome');
const messagesEl = document.getElementById('messages');
const scroll = document.getElementById('scroll');
const form = document.getElementById('form');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const sidebar = document.getElementById('sidebar');

// ---------- Helpers ----------
function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function scrollDown() { scroll.scrollTop = scroll.scrollHeight; }
function setBusy(v) { busy = v; sendBtn.disabled = v || input.value.trim().length === 0; }

// ---------- Mode & intake ----------
document.querySelectorAll('.mode').forEach(b => b.addEventListener('click', () => {
    mode = b.dataset.mode;
    document.querySelectorAll('.mode').forEach(x => x.setAttribute('aria-pressed', x === b));
    input.placeholder = MODE_PH[mode];
    input.focus();
}));
document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
    depth = b.dataset.depth;
    document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', x === b));
}));

// ---------- Render ----------
function addUser(text) {
    const d = document.createElement('div');
    d.className = 'msg user';
    d.textContent = text;
    messagesEl.appendChild(d);
}

function renderAnswer(a) {
    const srcCards = a.src.map(id => `
    <button class="src-card" data-src="${id}">
      <span>
        <span class="t">${esc(SOURCES[id].title)}</span><br>
        <span class="d">${esc(SOURCES[id].date)}</span>
      </span>
      <span class="tag ${SOURCES[id].status}">${SOURCES[id].status}</span>
    </button>`).join('');

    const paras = a.paras.map(p => {
        const cites = p.c.map(id => `<button class="cite" data-src="${id}" aria-label="Sumber ${id}">${id}</button>`).join('');
        return `<p>${esc(p.t)}${cites}</p>`;
    }).join('');

    const followups = a.followups.map(f => `<button class="followup">${esc(f)}</button>`).join('');

    const confidence = a.conf == null ? '' : `
    <div class="conf">Tingkat keyakinan
      <span class="conf-bar"><i style="width:${a.conf}%"></i></span>
      <b>${a.conf}%</b>
    </div>`;

    return `
    <div class="meta">
      <span class="chip-mode">${esc(MODE_LABEL[mode] || a.mode)}</span>
      <span>${esc(depth)} · Nasional</span>
    </div>
    <div class="ans">${paras}</div>

    <div class="block-label">Dasar hukum</div>
    <div class="src-list">${srcCards}</div>

    ${confidence}

    <details>
      <summary>Fakta yang digunakan dan asumsi</summary>
      <dl>
        <dt>Fakta</dt><dd>${esc(a.facts)}</dd>
        <dt>Asumsi</dt><dd>${esc(a.assumptions)}</dd>
      </dl>
    </details>

    <div class="verify"><b>Perlu verifikasi advokat:</b> ${esc(a.verify)}</div>

    <div class="actions">
      <button class="act" data-act="save">Simpan ke Matter</button>
      <button class="act" data-act="copy">Salin sitasi</button>
      <button class="act" data-act="revise">Minta revisi</button>
      <button class="act" data-act="verified">Tandai terverifikasi</button>
    </div>

    <div class="followups">${followups}</div>`;
}

function renderGuard() {
    return `
    <div class="meta"><span class="chip-mode">${esc(MODE_LABEL[mode])}</span><span>${esc(depth)} · Nasional</span></div>
    <div class="guard">
      Belum ditemukan dasar hukum yang cukup untuk mendukung kesimpulan ini.
      <small>Coba persempit pertanyaan, sebutkan peraturan yang relevan, atau simpan ke Matter untuk ditinjau advokat.</small>
    </div>
    <div class="actions">
      <button class="act" data-act="save">Simpan ke Matter</button>
      <button class="act" data-act="revise">Persempit pertanyaan</button>
    </div>`;
}

function addBot(html) {
    const d = document.createElement('div');
    d.className = 'msg bot';
    d.innerHTML = html;
    messagesEl.appendChild(d);
    return d;
}

// ---------- Ask (menampilkan tahapan kerja AI) ----------
const STAGES = ['Mencari sumber hukum…', 'Memeriksa status keberlakuan…', 'Menyusun jawaban dengan sitasi…'];

function ask(question) {
    if (!question || busy) return;
    welcome.classList.add('hidden');
    addUser(question);
    input.value = '';
    setBusy(true);

    const typing = document.createElement('div');
    typing.className = 'typing';
    typing.innerHTML = `<span class="pulse"></span><span id="stage">${STAGES[0]}</span>`;
    messagesEl.appendChild(typing);
    scrollDown();

    let i = 0;
    const timer = setInterval(() => {
        i = Math.min(i + 1, STAGES.length - 1);
        const s = document.getElementById('stage');
        if (s) s.textContent = STAGES[i];
    }, 600);

    fetch('/tanya', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pertanyaan: question })
    }).then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Pertanyaan gagal dikirim');
        return data;
    }).then(data => {
        clearInterval(timer);
        typing.remove();
        const answer = data.jawaban || 'Belum ada jawaban yang dapat ditampilkan.';
        const a = {
            mode: MODE_LABEL[mode],
            paras: [{ t: answer, c: [] }],
            src: [], conf: null,
            facts: 'Berdasarkan pertanyaan yang Anda kirim.',
            assumptions: 'Fakta tambahan belum diberikan.',
            verify: 'Periksa sitasi dan sumber asli sebelum digunakan.',
            followups: []
        };
        addBot(renderAnswer(a));
        setBusy(false);
        scrollDown();
    }).catch(() => {
        clearInterval(timer);
        typing.remove();
        addBot(renderGuard());
        setBusy(false);
        scrollDown();
    });
    scrollDown();
}

// ---------- Source drawer ----------
const drawer = document.getElementById('drawer');
const scrim = document.getElementById('scrim');
function openSource(id) {
    const s = SOURCES[id];
    if (!s) return;
    const tag = document.getElementById('d-tag');
    tag.className = 'tag ' + s.status;
    tag.textContent = s.status;
    document.getElementById('d-title').textContent = s.title;
    document.getElementById('d-date').textContent = s.date;
    document.getElementById('d-excerpt').textContent = s.excerpt;
    document.getElementById('d-note').textContent = s.note;
    drawer.classList.add('open');
    scrim.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
}
function closeDrawer() {
    drawer.classList.remove('open');
    scrim.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
}
document.getElementById('drawer-close').addEventListener('click', closeDrawer);
scrim.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

// ---------- Event delegation untuk pesan ----------
messagesEl.addEventListener('click', e => {
    const srcBtn = e.target.closest('[data-src]');
    if (srcBtn) { openSource(Number(srcBtn.dataset.src)); return; }

    const fu = e.target.closest('.followup');
    if (fu) { ask(fu.textContent); return; }

    const act = e.target.closest('.act');
    if (act) handleAct(act);
});

function handleAct(btn) {
    const kind = btn.dataset.act;
    if (kind === 'save') {
        btn.textContent = 'Tersimpan ke Matter ✓';
        btn.classList.add('on');
    } else if (kind === 'verified') {
        btn.textContent = 'Terverifikasi ✓';
        btn.classList.add('on');
    } else if (kind === 'copy') {
        const cites = [...btn.closest('.msg').querySelectorAll('.src-card .t')]
            .map((el, i) => `[${i + 1}] ${el.textContent}`).join('\n');
        navigator.clipboard?.writeText(cites).catch(() => { });
        btn.textContent = 'Tersalin ✓';
        btn.classList.add('on');
    } else if (kind === 'revise') {
        input.focus();
        input.placeholder = 'Tulis revisi atau pertanyaan lanjutan…';
    }
}

// ---------- Form & shortcuts ----------
input.addEventListener('input', () => setBusy(busy));
form.addEventListener('submit', e => {
    e.preventDefault();
    ask(input.value.trim());
});

document.querySelectorAll('.suggest').forEach(btn =>
    btn.addEventListener('click', () => ask(btn.dataset.q))
);

document.getElementById('new-chat').addEventListener('click', () => {
    messagesEl.innerHTML = '';
    welcome.classList.remove('hidden');
    scroll.scrollTop = 0;
    sidebar.classList.remove('open');
});

document.getElementById('menu').addEventListener('click', () => sidebar.classList.toggle('open'));
document.getElementById('logout').addEventListener('click', () => { window.location.href = '/logout'; });
