/* =============================================================================
   M-WIKI Editor – Wikilink-Vorschläge & Bild-Upload
   ============================================================================= */

let _topicCache = null;

async function loadTopics() {
    if (_topicCache) return _topicCache;
    try {
        const res = await fetch("/api/topics", { credentials: "same-origin" });
        if (!res.ok) throw new Error("topics fetch failed");
        _topicCache = await res.json();
    } catch (e) {
        console.error(e);
        _topicCache = [];
    }
    return _topicCache;
}

/**
 * Findet Vorkommen von Topic-Titeln im Text die NICHT bereits in [[...]] sind.
 * Längere Titel werden bevorzugt (greedy).
 */
function findLinkOpportunities(text, topics, currentTitle) {
    if (!text) return [];
    // existierende Wikilink-Regionen markieren
    const ranges = [];
    const linkRe = /\[\[[^\]]+?\]\]/g;
    let m;
    while ((m = linkRe.exec(text)) !== null) {
        ranges.push([m.index, m.index + m[0].length]);
    }
    const inLink = (i) => ranges.some(([a, b]) => i >= a && i < b);

    // Topics nach Länge sortieren (lange zuerst)
    const sorted = [...topics].sort((a, b) => b.title.length - a.title.length);

    const hits = new Map(); // title -> { topic, count, firstPos }

    for (const t of sorted) {
        if (!t.title || t.title.length < 2) continue;
        if (currentTitle && t.title.toLowerCase() === currentTitle.toLowerCase()) continue;
        const esc = t.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const re = new RegExp(`(?<![\\p{L}\\p{N}_])${esc}(?![\\p{L}\\p{N}_])`, "giu");
        let mm;
        while ((mm = re.exec(text)) !== null) {
            if (inLink(mm.index)) continue;
            const entry = hits.get(t.title) || { topic: t, count: 0, firstPos: mm.index };
            entry.count++;
            hits.set(t.title, entry);
        }
    }

    return Array.from(hits.values()).sort((a, b) => a.firstPos - b.firstPos);
}

function renderSuggestions(textarea, suggestions) {
    const list = document.getElementById("suggestions");
    if (!list) return;

    if (!suggestions.length) {
        list.innerHTML = '<li class="muted small">Keine passenden Topics im Text.</li>';
        return;
    }

    list.innerHTML = "";
    for (const s of suggestions) {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.innerHTML = `[[${escapeHtml(s.topic.title)}]] <span class="sug-count">${s.count}×</span>`;
        btn.addEventListener("click", () => convertOccurrences(textarea, s.topic.title));
        li.appendChild(btn);
        list.appendChild(li);
    }
}

function convertOccurrences(textarea, title) {
    const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(?<![\\p{L}\\p{N}_\\[])${esc}(?![\\p{L}\\p{N}_\\]])`, "gu");
    const before = textarea.value;
    // skip occurences die schon in [[...]] sind
    let result = "";
    let lastEnd = 0;
    // Sammeln aller [[...]] Regionen
    const linkRe = /\[\[[^\]]+?\]\]/g;
    const ranges = [];
    let m;
    while ((m = linkRe.exec(before)) !== null) {
        ranges.push([m.index, m.index + m[0].length]);
    }
    const inLink = (i) => ranges.some(([a, b]) => i >= a && i < b);

    let mm;
    while ((mm = re.exec(before)) !== null) {
        if (inLink(mm.index)) continue;
        result += before.slice(lastEnd, mm.index);
        result += `[[${title}]]`;
        lastEnd = mm.index + mm[0].length;
    }
    result += before.slice(lastEnd);

    textarea.value = result;
    textarea.focus();
    triggerInput(textarea);
}

function triggerInput(el) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

function debounce(fn, wait) {
    let to;
    return (...args) => {
        clearTimeout(to);
        to = setTimeout(() => fn(...args), wait);
    };
}

/* ----------------------- Bild-Upload --------------------------------------- */

function insertAtCursor(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.slice(0, start);
    const after = textarea.value.slice(end);
    textarea.value = before + text + after;
    const pos = start + text.length;
    textarea.selectionStart = textarea.selectionEnd = pos;
    textarea.focus();
    triggerInput(textarea);
}

async function uploadFile(file, textarea, statusEl) {
    if (!file.type.startsWith("image/")) {
        statusEl.textContent = "Nur Bilder erlaubt.";
        return;
    }
    statusEl.textContent = "Lade hoch…";
    const fd = new FormData();
    fd.append("file", file);
    if (window.MWIKI_TOPIC_ID) fd.append("topic_id", window.MWIKI_TOPIC_ID);

    try {
        const res = await fetch("/upload", {
            method: "POST",
            body: fd,
            credentials: "same-origin",
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        const data = await res.json();
        insertAtCursor(textarea, `\n![${file.name}](${data.url})\n`);
        statusEl.textContent = `✓ Hochgeladen: ${file.name}`;
        setTimeout(() => { statusEl.textContent = ""; }, 4000);
    } catch (e) {
        statusEl.textContent = "Fehler: " + e.message;
    }
}

/* ----------------------- Editor Init --------------------------------------- */

async function initEditor() {
    const textarea = document.getElementById("contentArea");
    if (!textarea) return;
    const titleInput = document.getElementById("titleInput");
    const statusEl = document.getElementById("uploadStatus");
    const fileInput = document.getElementById("imageUpload");
    const zone = document.getElementById("uploadZone");

    const topics = await loadTopics();

    const update = debounce(() => {
        const hits = findLinkOpportunities(textarea.value, topics, titleInput?.value);
        renderSuggestions(textarea, hits);
    }, 280);

    textarea.addEventListener("input", update);
    if (titleInput) titleInput.addEventListener("input", update);
    update();

    /* Tab → 4 spaces für code-blöcke */
    textarea.addEventListener("keydown", (e) => {
        if (e.key === "Tab" && !e.shiftKey) {
            e.preventDefault();
            insertAtCursor(textarea, "    ");
        }
    });

    /* Upload Handlers */
    if (fileInput) {
        fileInput.addEventListener("change", (e) => {
            const f = e.target.files[0];
            if (f) uploadFile(f, textarea, statusEl);
        });
    }

    if (zone) {
        ["dragenter", "dragover"].forEach(ev => {
            zone.addEventListener(ev, (e) => {
                e.preventDefault(); e.stopPropagation();
                zone.classList.add("dragover");
            });
        });
        ["dragleave", "drop"].forEach(ev => {
            zone.addEventListener(ev, (e) => {
                e.preventDefault(); e.stopPropagation();
                zone.classList.remove("dragover");
            });
        });
        zone.addEventListener("drop", (e) => {
            const f = e.dataTransfer.files[0];
            if (f) uploadFile(f, textarea, statusEl);
        });
    }

    /* Drop direkt auf Textarea */
    textarea.addEventListener("dragover", (e) => e.preventDefault());
    textarea.addEventListener("drop", (e) => {
        const f = e.dataTransfer.files[0];
        if (f && f.type.startsWith("image/")) {
            e.preventDefault();
            uploadFile(f, textarea, statusEl);
        }
    });

    /* Paste Bilder aus Clipboard */
    textarea.addEventListener("paste", (e) => {
        const items = e.clipboardData?.items || [];
        for (const it of items) {
            if (it.kind === "file" && it.type.startsWith("image/")) {
                const f = it.getAsFile();
                if (f) {
                    e.preventDefault();
                    uploadFile(f, textarea, statusEl);
                    break;
                }
            }
        }
    });

    /* Strg+S → Speichern */
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
            e.preventDefault();
            document.getElementById("editForm")?.submit();
        }
    });
}

window.initEditor = initEditor;
