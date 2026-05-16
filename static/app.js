/* =============================================================================
   M-WIKI Mobile SPA
   Routing via hash:
     #/                       → Startseite
     #/topic/123              → Topic anzeigen
     #/topic/new              → Neues Topic
     #/topic/new?title=X      → Neues Topic mit vorausgefülltem Titel
     #/topic/123/edit         → Bearbeiten
     #/category/45            → Kategorie
     #/search?q=…             → Suche
   ============================================================================= */

(function () {
    "use strict";

    const main = document.getElementById("appMain");
    const drawer = document.getElementById("drawer");
    const drawerBackdrop = document.getElementById("drawerBackdrop");
    const drawerClose = document.getElementById("drawerClose");
    const drawerTree = document.getElementById("drawerTree");
    const navToggle = document.getElementById("navToggle");
    const searchToggle = document.getElementById("searchToggle");
    const searchBar = document.getElementById("searchBar");
    const searchInput = document.getElementById("searchInput");
    const goDesktopLink = document.getElementById("goDesktopLink");

    let _topicCache = null;
    let _treeCache = null;

    /* ---------- helpers ---------- */

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[c]));
    }

    function toast(msg) {
        const t = document.createElement("div");
        t.className = "toast";
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 2500);
    }

    async function api(path, opts = {}) {
        opts.credentials = "same-origin";
        opts.headers = Object.assign({ "Accept": "application/json" }, opts.headers || {});
        const r = await fetch(path, opts);
        if (r.status === 401) {
            location.href = "/login?next=/app/";
            throw new Error("unauthorized");
        }
        return r;
    }

    async function getJSON(path) {
        const r = await api(path);
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${r.status}`);
        }
        return r.json();
    }

    function fmtDate(s) {
        if (!s) return "";
        return s.slice(0, 16).replace("T", " ");
    }

    function parseHashQuery(h) {
        const i = h.indexOf("?");
        if (i < 0) return {};
        const out = {};
        h.slice(i + 1).split("&").forEach((p) => {
            const [k, v] = p.split("=");
            if (k) out[decodeURIComponent(k)] = decodeURIComponent(v || "");
        });
        return out;
    }

    /* ---------- Drawer ---------- */

    function closeDrawer() {
        drawer.classList.add("hidden");
        drawer.setAttribute("aria-hidden", "true");
        document.body.classList.remove("drawer-open");
    }
    function openDrawer() {
        refreshDrawer();
        drawer.classList.remove("hidden");
        drawer.setAttribute("aria-hidden", "false");
        document.body.classList.add("drawer-open");
    }

    navToggle.addEventListener("click", () => {
        drawer.classList.contains("hidden") ? openDrawer() : closeDrawer();
    });
    drawerBackdrop.addEventListener("click", closeDrawer);
    drawerClose.addEventListener("click", closeDrawer);

    // Escape closes drawer
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !drawer.classList.contains("hidden")) {
            closeDrawer();
        }
    });

    searchToggle.addEventListener("click", () => {
        searchBar.classList.toggle("hidden");
        if (!searchBar.classList.contains("hidden")) searchInput.focus();
    });

    searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            const q = searchInput.value.trim();
            if (q) {
                location.hash = "#/search?q=" + encodeURIComponent(q);
                searchBar.classList.add("hidden");
            }
        }
    });

    // Drawer-Aktionen (Buttons mit data-route)
    drawer.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-route]");
        if (btn) {
            e.preventDefault();
            const r = btn.dataset.route;
            if (r === "home") location.hash = "#/";
            else if (r === "new") location.hash = "#/topic/new";
            closeDrawer();
        }
        const link = e.target.closest("a[data-nav]");
        if (link) {
            e.preventDefault();
            location.hash = link.getAttribute("href");
            closeDrawer();
        }
    });

    // Wenn User auf "Desktop-Version" klickt: prefer_desktop-Cookie wird vom
    // Server gesetzt (?d=1). Hier nur zur Sicherheit: Drawer schließen.
    if (goDesktopLink) {
        goDesktopLink.addEventListener("click", () => closeDrawer());
    }

    /* ---------- Drawer Tree ---------- */

    async function refreshDrawer() {
        if (!_treeCache) {
            try {
                _treeCache = await getJSON("/api/tree");
            } catch (e) { return; }
        }
        const html = [];
        function renderCat(c) {
            html.push(`<div class="cat-block">
                <a class="cat-name" data-nav href="#/category/${c.id}">${esc(c.name)}</a>`);
            for (const t of c.topics) {
                html.push(`<a class="topic-link" data-nav href="#/topic/${t.id}">${esc(t.title)}</a>`);
            }
            for (const ch of c.children) renderCat(ch);
            html.push(`</div>`);
        }
        for (const root of _treeCache.roots) renderCat(root);
        if (_treeCache.uncategorized.length) {
            html.push(`<div class="cat-block"><span class="cat-name">Ohne Kategorie</span>`);
            for (const t of _treeCache.uncategorized) {
                html.push(`<a class="topic-link" data-nav href="#/topic/${t.id}">${esc(t.title)}</a>`);
            }
            html.push(`</div>`);
        }
        drawerTree.innerHTML = html.join("") ||
            '<p class="empty-hint">Keine Topics.</p>';
    }

    function invalidateCaches() {
        _topicCache = null;
        _treeCache = null;
    }

    /* ---------- Wikilink Rendering Helper ---------- */
    // rendered HTML kommt schon mit <a class="wikilink">.
    // Wir wandeln /topic/123 und /topic/new?title=X in Hash-Routes.
    function bindLinks(scope) {
        scope.querySelectorAll('a.wikilink').forEach(a => {
            const href = a.getAttribute("href") || "";
            if (href.startsWith("/topic/new")) {
                // broken link → SPA-Route mit Query
                const qIdx = href.indexOf("?");
                const newHash = qIdx >= 0
                    ? "#/topic/new" + href.slice(qIdx)
                    : "#/topic/new";
                a.addEventListener("click", (e) => {
                    e.preventDefault();
                    location.hash = newHash;
                });
            } else if (/^\/topic\/\d+$/.test(href)) {
                a.addEventListener("click", (e) => {
                    e.preventDefault();
                    location.hash = "#" + href;
                });
            }
        });
    }

    /* ---------- Routes ---------- */

    async function viewHome() {
        main.innerHTML = `<div class="loader">Lade…</div>`;
        try {
            const recent = await getJSON("/api/recent?limit=20");
            let html = `
                <section class="hero-app">
                    <h1>${esc(window.WIKI_TITLE)}</h1>
                    <p>Internes Wiki</p>
                </section>
                <h2 class="section-h">Zuletzt bearbeitet</h2>
            `;
            if (recent.length === 0) {
                html += `<p class="empty">Noch keine Topics. <a data-nav href="#/topic/new">Eines anlegen?</a></p>`;
            } else {
                html += `<ul class="list-cards">`;
                for (const t of recent) {
                    html += `<li><a data-nav href="#/topic/${t.id}">${esc(t.title)}<span class="meta">${fmtDate(t.updated_at)}</span></a></li>`;
                }
                html += `</ul>`;
            }
            main.innerHTML = html;
            bindNavLinks();
        } catch (e) {
            main.innerHTML = `<div class="err-msg">Fehler: ${esc(e.message)}</div>`;
        }
    }

    async function viewTopic(id) {
        main.innerHTML = `<div class="loader">Lade…</div>`;
        try {
            const t = await getJSON(`/api/topic/${id}`);
            let html = `
                <article class="topic-view">
                    <div class="crumbs">
                        <a data-nav href="#/">Start</a>
                        ${t.category_name ? `&rsaquo; <a data-nav href="#/category/${t.category_id}">${esc(t.category_name)}</a>` : ""}
                        &rsaquo; <span>${esc(t.title)}</span>
                    </div>
                    <h1 class="title">${esc(t.title)}</h1>
                    <div class="meta">angelegt ${fmtDate(t.created_at)}${t.author ? " · von " + esc(t.author) : ""} · zuletzt ${fmtDate(t.updated_at)}</div>
                    <div class="body">${t.rendered || '<p class="empty"><em>Kein Inhalt.</em></p>'}</div>
                    <div class="actions-row">
                        <a class="btn" data-nav href="#/topic/${t.id}/edit">Bearbeiten</a>
                        <button class="btn btn-danger" data-action="delete-topic" data-id="${t.id}">Löschen</button>
                    </div>
                    <section class="comments-block">
                        <h2 class="section-h">Kommentare (${t.comments.length})</h2>
                        <div id="commentList"></div>
                        <textarea class="comment-input" id="newComment" placeholder="Kommentar schreiben…" maxlength="10000"></textarea>
                        <button class="btn btn-block" data-action="add-comment" data-id="${t.id}">Kommentieren</button>
                    </section>
                </article>
            `;
            main.innerHTML = html;
            renderComments(t.comments);
            bindLinks(main);
            bindNavLinks();
            main.querySelector('[data-action="delete-topic"]').addEventListener("click", async () => {
                if (!confirm("Topic löschen?")) return;
                const r = await api(`/topic/${id}/delete`, { method: "POST", body: new FormData() });
                if (r.ok || r.redirected) {
                    invalidateCaches();
                    location.hash = "#/";
                }
            });
            main.querySelector('[data-action="add-comment"]').addEventListener("click", async () => {
                const txt = document.getElementById("newComment").value.trim();
                if (!txt) return;
                const fd = new FormData();
                fd.append("content", txt);
                const r = await api(`/topic/${id}/comment`, { method: "POST", body: fd });
                if (r.ok || r.redirected) viewTopic(id);
            });
        } catch (e) {
            main.innerHTML = `<div class="err-msg">${esc(e.message)}</div>`;
        }
    }

    function renderComments(comments) {
        const wrap = document.getElementById("commentList");
        if (!comments.length) {
            wrap.innerHTML = `<p class="empty" style="margin:0 0 1em">Noch keine Kommentare.</p>`;
            return;
        }
        wrap.innerHTML = comments.map(c => `
            <div class="comment-card">
                <button class="del" data-cid="${c.id}" title="Löschen">×</button>
                <span class="author">${esc(c.author)}</span>
                <span class="date">${fmtDate(c.created_at)}</span>
                <div class="body">${esc(c.content)}</div>
            </div>
        `).join("");
        wrap.querySelectorAll(".del").forEach(b => {
            b.addEventListener("click", async () => {
                if (!confirm("Kommentar löschen?")) return;
                const r = await api(`/comment/${b.dataset.cid}/delete`, {
                    method: "POST", body: new FormData()
                });
                if (r.ok || r.redirected) {
                    const m = location.hash.match(/#\/topic\/(\d+)/);
                    if (m) viewTopic(m[1]);
                }
            });
        });
    }

    async function viewCategory(id) {
        main.innerHTML = `<div class="loader">Lade…</div>`;
        try {
            // immer frisch laden, falls neu erstellt
            _treeCache = await getJSON("/api/tree");
            function findCat(nodes) {
                for (const n of nodes) {
                    if (String(n.id) === String(id)) return n;
                    const sub = findCat(n.children);
                    if (sub) return sub;
                }
                return null;
            }
            const cat = findCat(_treeCache.roots);
            if (!cat) {
                main.innerHTML = `<div class="err-msg">Kategorie nicht gefunden</div>`;
                return;
            }
            let html = `
                <article class="topic-view">
                    <div class="crumbs"><a data-nav href="#/">Start</a> &rsaquo; <span>${esc(cat.name)}</span></div>
                    <h1 class="title">${esc(cat.name)}</h1>
            `;
            if (cat.children.length) {
                html += `<h2 class="section-h">Unterkategorien</h2><ul class="list-cards">`;
                for (const s of cat.children) html += `<li><a data-nav href="#/category/${s.id}">${esc(s.name)}</a></li>`;
                html += `</ul>`;
            }
            html += `<h2 class="section-h">Topics</h2>`;
            if (cat.topics.length === 0) {
                html += `<p class="empty">Keine Topics.</p>`;
            } else {
                html += `<ul class="list-cards">`;
                for (const t of cat.topics) html += `<li><a data-nav href="#/topic/${t.id}">${esc(t.title)}</a></li>`;
                html += `</ul>`;
            }
            html += `</article>`;
            main.innerHTML = html;
            bindNavLinks();
        } catch (e) {
            main.innerHTML = `<div class="err-msg">${esc(e.message)}</div>`;
        }
    }

    async function viewEdit(id, presetTitle) {
        main.innerHTML = `<div class="loader">Lade…</div>`;
        const isNew = id === "new";
        let topic = { id: null, title: presetTitle || "", content: "", category_id: null };
        let cats = [];
        try {
            if (!isNew) {
                topic = await getJSON(`/api/topic/${id}`);
            }
            _treeCache = await getJSON("/api/tree");
            function flat(nodes, out = [], depth = 0) {
                for (const n of nodes) {
                    out.push({ id: n.id, name: "—".repeat(depth) + " " + n.name });
                    flat(n.children, out, depth + 1);
                }
                return out;
            }
            cats = flat(_treeCache.roots);
            if (!_topicCache) _topicCache = await getJSON("/api/topics");
        } catch (e) {
            main.innerHTML = `<div class="err-msg">${esc(e.message)}</div>`;
            return;
        }

        main.innerHTML = `
            <article class="topic-view">
                <h1 class="title">${isNew ? "Neues Topic" : "Bearbeiten"}</h1>
                <form class="app-form" id="appEditForm">
                    <label>
                        <span class="lbl">Titel</span>
                        <input type="text" name="title" id="mTitle" required maxlength="200" value="${esc(topic.title)}">
                    </label>
                    <label>
                        <span class="lbl">Kategorie</span>
                        <select name="category_id" id="mCat">
                            <option value="">— ohne —</option>
                            ${cats.map(c => `<option value="${c.id}" ${String(topic.category_id) === String(c.id) ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
                        </select>
                    </label>
                    <label>
                        <span class="lbl">Inhalt (Markdown + [[Wikilinks]])</span>
                        <textarea name="content" id="mContent" rows="14" maxlength="200000">${esc(topic.content)}</textarea>
                    </label>
                    <div id="mSuggest"></div>
                    <label class="upload-mini">
                        <input type="file" id="mUpload" accept="image/*" hidden>
                        📷 Bild hochladen
                    </label>
                    <div id="mUploadStatus" style="color:var(--text-dim);font-size:0.85em;margin-top:0.3em"></div>
                    <div class="actions-row">
                        <button type="submit" class="btn btn-primary btn-block">${isNew ? "Anlegen" : "Speichern"}</button>
                    </div>
                </form>
            </article>
        `;

        const form = document.getElementById("appEditForm");
        const titleEl = document.getElementById("mTitle");
        const contentEl = document.getElementById("mContent");
        const sugEl = document.getElementById("mSuggest");
        const uploadEl = document.getElementById("mUpload");
        const uploadStatus = document.getElementById("mUploadStatus");

        function updateSuggestions() {
            const text = contentEl.value;
            const currentTitle = titleEl.value;
            if (!text) { sugEl.innerHTML = ""; return; }
            const linkRe = /\[\[[^\]]+?\]\]/g;
            const ranges = [];
            let m;
            while ((m = linkRe.exec(text)) !== null) ranges.push([m.index, m.index + m[0].length]);
            const inLink = (i) => ranges.some(([a, b]) => i >= a && i < b);

            const sorted = [..._topicCache].sort((a, b) => b.title.length - a.title.length);
            const hits = new Map();
            for (const t of sorted) {
                if (!t.title || t.title.length < 2) continue;
                if (currentTitle && t.title.toLowerCase() === currentTitle.toLowerCase()) continue;
                const escTitle = t.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
                let re;
                try {
                    re = new RegExp(`(?<![\\p{L}\\p{N}_])${escTitle}(?![\\p{L}\\p{N}_])`, "giu");
                } catch (_) {
                    re = new RegExp(`(^|[^\\w])${escTitle}(?=[^\\w]|$)`, "gi");
                }
                let mm;
                while ((mm = re.exec(text)) !== null) {
                    if (inLink(mm.index)) continue;
                    const ent = hits.get(t.title) || { topic: t, count: 0 };
                    ent.count++;
                    hits.set(t.title, ent);
                }
            }
            if (!hits.size) { sugEl.innerHTML = ""; return; }
            const items = Array.from(hits.values()).slice(0, 8);
            sugEl.innerHTML = `<div class="suggest-pop">
                <h4>Vorschläge</h4>
                <ul>${items.map(h => `<li><button type="button" data-title="${esc(h.topic.title)}">→ [[${esc(h.topic.title)}]] (${h.count}×)</button></li>`).join("")}</ul>
            </div>`;
            sugEl.querySelectorAll("button").forEach(b => {
                b.addEventListener("click", () => {
                    convertOccurrences(contentEl, b.dataset.title);
                    updateSuggestions();
                });
            });
        }

        function convertOccurrences(ta, title) {
            const before = ta.value;
            const escTitle = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            let re;
            try {
                re = new RegExp(`(?<![\\p{L}\\p{N}_\\[])${escTitle}(?![\\p{L}\\p{N}_\\]])`, "gu");
            } catch (_) {
                re = new RegExp(`(^|[^\\w\\[])${escTitle}(?=[^\\w\\]]|$)`, "g");
            }
            const linkRe = /\[\[[^\]]+?\]\]/g;
            const ranges = [];
            let m;
            while ((m = linkRe.exec(before)) !== null) ranges.push([m.index, m.index + m[0].length]);
            const inLink = (i) => ranges.some(([a, b]) => i >= a && i < b);
            let result = ""; let lastEnd = 0; let mm;
            while ((mm = re.exec(before)) !== null) {
                if (inLink(mm.index)) continue;
                // Bei fallback-regex steht mm[1] für leading char, das wir behalten müssen
                const leading = mm[1] !== undefined ? mm[1] : "";
                const matchStart = mm.index + leading.length;
                result += before.slice(lastEnd, matchStart) + `[[${title}]]`;
                lastEnd = matchStart + title.length;
            }
            result += before.slice(lastEnd);
            ta.value = result;
        }

        let to;
        const trigger = () => {
            clearTimeout(to);
            to = setTimeout(updateSuggestions, 280);
        };
        contentEl.addEventListener("input", trigger);
        titleEl.addEventListener("input", trigger);
        updateSuggestions();

        uploadEl.addEventListener("change", async (e) => {
            const f = e.target.files[0];
            if (!f) return;
            uploadStatus.textContent = "Lade hoch…";
            const fd = new FormData();
            fd.append("file", f);
            if (topic.id) fd.append("topic_id", topic.id);
            try {
                const r = await api("/upload", { method: "POST", body: fd });
                if (!r.ok) {
                    const err = await r.json().catch(() => ({}));
                    throw new Error(err.error || "Upload fehlgeschlagen");
                }
                const d = await r.json();
                const cur = contentEl.value;
                const start = contentEl.selectionStart || cur.length;
                const ins = `\n![${f.name}](${d.url})\n`;
                contentEl.value = cur.slice(0, start) + ins + cur.slice(start);
                uploadStatus.textContent = "✓ " + f.name;
                setTimeout(() => uploadStatus.textContent = "", 3000);
            } catch (err) {
                uploadStatus.textContent = "Fehler: " + err.message;
            }
            uploadEl.value = "";  // reset, sonst kein change-event bei gleicher Datei
        });

        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(form);
            const url = isNew ? "/topic/new" : `/topic/${id}/edit`;
            try {
                const r = await api(url, { method: "POST", body: fd });
                if (r.ok || r.redirected) {
                    invalidateCaches();
                    // Beim Anlegen Server redirected zu /topic/{newId}
                    if (r.redirected) {
                        const m = r.url.match(/\/topic\/(\d+)(?:[?#]|$)/);
                        if (m) {
                            location.hash = `#/topic/${m[1]}`;
                            return;
                        }
                    }
                    // Edit-Pfad: zurück zum Topic
                    if (!isNew) {
                        location.hash = `#/topic/${id}`;
                    } else {
                        // Fallback: neuestes Topic finden
                        location.hash = "#/";
                    }
                } else {
                    const err = await r.json().catch(() => ({}));
                    toast("Fehler: " + (err.error || r.status));
                }
            } catch (err) {
                toast("Fehler: " + err.message);
            }
        });
    }

    async function viewSearch(q) {
        main.innerHTML = `<div class="loader">Suche…</div>`;
        try {
            const data = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
            let render = `<h1 class="title" style="font-family:var(--font-serif);font-size:1.5rem">Suche: „${esc(q)}"</h1>`;
            render += `<p style="color:var(--text-dim);font-size:0.9em">${data.count} Treffer</p>`;
            if (!data.results.length) {
                render += `<p class="empty">Nichts gefunden.</p>`;
            } else {
                render += `<ul class="list-cards">`;
                for (const r of data.results) {
                    render += `<li><a data-nav href="#/topic/${r.id}">${esc(r.title)}`;
                    if (r.snippet) render += `<span class="meta">…${esc(r.snippet)}…</span>`;
                    render += `</a></li>`;
                }
                render += `</ul>`;
            }
            main.innerHTML = render;
            bindNavLinks();
        } catch (e) {
            main.innerHTML = `<div class="err-msg">${esc(e.message)}</div>`;
        }
    }

    function bindNavLinks() {
        main.querySelectorAll("a[data-nav]").forEach(a => {
            a.addEventListener("click", (e) => {
                e.preventDefault();
                location.hash = a.getAttribute("href");
            });
        });
    }

    /* ---------- Router ---------- */

    function route() {
        closeDrawer();
        main.scrollTop = 0;
        window.scrollTo(0, 0);
        const h = location.hash || "#/";
        let m;
        if (h === "#/" || h === "" || h === "#") return viewHome();
        if ((m = h.match(/^#\/topic\/(\d+)\/edit$/))) return viewEdit(m[1]);
        if (h.startsWith("#/topic/new")) {
            const q = parseHashQuery(h);
            return viewEdit("new", q.title || "");
        }
        if ((m = h.match(/^#\/topic\/(\d+)$/))) return viewTopic(m[1]);
        if ((m = h.match(/^#\/category\/(\d+)$/))) return viewCategory(m[1]);
        if (h.startsWith("#/search")) {
            const q = parseHashQuery(h);
            return viewSearch(q.q || "");
        }
        viewHome();
    }

    window.addEventListener("hashchange", route);
    route();
})();
