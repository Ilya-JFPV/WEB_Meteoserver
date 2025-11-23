/* client.js — маркеры по статусам + Hc5 легенда + подсказки к сериям */

(() => {
  // -------------------- utils --------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $all = (sel, root = document) => [...root.querySelectorAll(sel)];
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return await r.json();
  }
  async function postJSON(url, obj) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(obj),
    });
    if (!r.ok) throw new Error(await r.text());
    return await r.json();
  }
  const fmt = v => (v == null || Number.isNaN(v) ? "—" : (Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1)));
  const fmtTs = ts => ts ? new Date(ts * 1000).toLocaleString() : "—";

  // -------------------- series meta --------------------
  const COLORS = {
    Sa0:"#1f77b4", Ta1:"#ff7f0e", Hr1:"#2ca02c", Pa2:"#9467bd",
    Or3:"#17becf", Rt4:"#d62728", Ri4:"#bcbd22", Ra4:"#8c564b", Rs4:"#e377c2", Hc5:"#7f7f7f"
  };
  const LABELS = {
    Sa0:"Ветер (м/с)", Ta1:"Темп. (°C)", Hr1:"Влажн. (%)", Pa2:"Давл. (гПа)",
    Or3:"Осадки (инт.)", Rt4:"Инт. осадков", Ri4:"Интегр. осадков",
    Ra4:"Сумма (сутки)", Rs4:"Сумма (период)", Hc5:"Облачность (код)"
  };
  const UNITS = { Sa0:"м/с", Ta1:"°C", Hr1:"%", Pa2:"гПа", Or3:"", Rt4:"", Ri4:"", Ra4:"", Rs4:"", Hc5:"" };

  const WINDOW_PRESETS = [
    { value: 30, label: "30 мин" },
    { value: 360, label: "6 часов" },
    { value: 1440, label: "24 часа" },
  ];

  let currentWindowMinutes = WINDOW_PRESETS[1].value;
  const refreshUI = { last: null, err: null };

  // краткие описания для подсказок (подкорректируем под твой протокол при необходимости)
  const SERIES_INFO = {
    Sa0: "Средняя скорость ветра",
    Ta1: "Температура воздуха",
    Hr1: "Отн. влажность",
    Pa2: "Атмосферное давление",
    Or3: "Факт осадков (детектор/инт.)",
    Rt4: "Интенсивность осадков (текущая)",
    Ri4: "Нарастающий итог осадков",
    Ra4: "Суточная сумма осадков",
    Rs4: "Сумма осадков за период окна",
    Hc5: "Облачность: кол-во слоёв и их высоты"
  };

  async function runInBatches(items, batchSize, worker){
    for (let i = 0; i < items.length; i += batchSize){
      const slice = items.slice(i, i + batchSize);
      await Promise.allSettled(slice.map(worker));
    }
  }

  const STATUS_HINTS = {
    Er3:"Ошибки по блоку Hc5 (пример)",
    Er5:"Ошибки по блоку Ra/Rs (пример)",
    St5:"Диагностический код (HEX)"
  };

  // -------------------- sparkline --------------------
  function drawSparkline(canvas, ts, ys, color, unit) {
    const cssW = canvas.clientWidth || 320;
    const cssH = canvas.clientHeight || 120;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(cssW * dpr));
    canvas.height = Math.max(1, Math.floor(cssH * dpr));
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    ctx.clearRect(0,0,cssW,cssH);
    ctx.fillStyle = "#fff"; ctx.fillRect(0,0,cssW,cssH);
    ctx.strokeStyle = "#e6e6e6"; ctx.strokeRect(.5,.5,cssW-1,cssH-1);

    canvas._spark = null;
    if (!ys?.length) { ctx.fillStyle="#888"; ctx.fillText("Нет данных", 10, cssH/2); return; }
    let min=Infinity,max=-Infinity;
    ys.forEach(v=>{ if(v!=null&&!Number.isNaN(v)){ if(v<min)min=v; if(v>max)max=v; }});
    if(!isFinite(min)||!isFinite(max)){ ctx.fillStyle="#888"; ctx.fillText("Нет валидных точек", 10, cssH/2); return; }
    if(min===max){ min-=1; max+=1; }

    const pad=10, W=cssW-pad*2, H=cssH-pad*2;
    const coords = [];
    ctx.strokeStyle=color; ctx.lineWidth=1.5; ctx.beginPath();
    ys.forEach((v,i)=>{
      const x = pad + (i*W)/Math.max(1,ys.length-1);
      const y = pad + (1-(v-min)/(max-min))*H;
      coords.push({ x, y, ts: ts?.[i], value: v });
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    });
    ctx.stroke();

    const last = ys[ys.length-1];
    const lx = pad + ((ys.length-1)*W)/Math.max(1,ys.length-1);
    const ly = pad + (1-(last-min)/(max-min))*H;
    ctx.fillStyle=color; ctx.beginPath(); ctx.arc(lx,ly,3,0,Math.PI*2); ctx.fill();

    ctx.fillStyle="#333"; ctx.font="12px system-ui, sans-serif";
    ctx.fillText(`${fmt(last)}${unit?` ${unit}`:""}`, Math.min(cssW-60,lx+6), Math.max(12, ly-6));

    canvas._spark = { coords, color, unit };
  }

  const sparkTip = (() => {
    const el = document.createElement("div");
    el.style.position = "fixed";
    el.style.pointerEvents = "none";
    el.style.background = "rgba(0,0,0,.75)";
    el.style.color = "#fff";
    el.style.padding = "6px 8px";
    el.style.borderRadius = "6px";
    el.style.font = "12px system-ui, sans-serif";
    el.style.zIndex = 2000;
    el.style.display = "none";
    document.body.appendChild(el);
    return el;
  })();

  function showSparkTip(text, x, y) {
    sparkTip.textContent = text;
    sparkTip.style.display = "block";
    sparkTip.style.left = `${x + 12}px`;
    sparkTip.style.top = `${y + 12}px`;
  }
  function hideSparkTip() { sparkTip.style.display = "none"; }

  function bindSparklineTooltip(canvas) {
    const handler = (ev) => {
      const data = canvas._spark;
      if (!data || !data.coords?.length) { hideSparkTip(); return; }
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      let best = null;
      for (const c of data.coords) {
        const dx = c.x - x, dy = c.y - y;
        const dist = dx*dx + dy*dy;
        if (best === null || dist < best.dist) best = { dist, c };
      }
      if (!best || best.c.value == null || Number.isNaN(best.c.value)) { hideSparkTip(); return; }
      const tsLabel = fmtTs(best.c.ts);
      const valLabel = `${fmt(best.c.value)}${data.unit ? ` ${data.unit}` : ""}`;
      showSparkTip(`${tsLabel}\n${valLabel}`, ev.clientX, ev.clientY);
    };
    canvas.addEventListener("mousemove", handler);
    canvas.addEventListener("mouseleave", hideSparkTip);
  }

  async function renderSeriesBox(el, stationId, minutes, fields, units) {
    el.innerHTML = `<div class="series-hint">Загружаю…</div>`;
    let data;
    try {
      const url = `/measurements/range?station_id=${encodeURIComponent(stationId)}&minutes=${minutes}&fields=${fields.join(",")}&units=${units}`;
      data = await getJSON(url);
    } catch (e) {
      console.error(e);
      el.innerHTML = `<div class="series-error">Ошибка загрузки данных</div>`;
      return;
    }

    const tsCount = data.ts?.length || 0;
    el.innerHTML = "";
    const summary = document.createElement("div");
    summary.className = "series-summary";
    summary.textContent = tsCount ? `Точек: ${tsCount}` : "Нет данных в выбранном окне.";
    el.appendChild(summary);

    for (const f of fields) {
      const row = document.createElement("div"); row.className="series-row";
      const title = document.createElement("div");
      title.className="series-title";
      title.textContent = (LABELS[f] || f);
      title.title = (SERIES_INFO[f] ? `${SERIES_INFO[f]}${UNITS[f] ? `, ед.: ${UNITS[f]}` : ""}` : "");
      const cv = document.createElement("canvas"); cv.className="series-canvas";
      row.appendChild(title); row.appendChild(cv); el.appendChild(row);

      const unit = UNITS[f] || "";
      requestAnimationFrame(()=> { drawSparkline(cv, data.ts||[], data.series?.[f]||[], COLORS[f]||"#444", unit); bindSparklineTooltip(cv); });
    }
  }

  // ---------- статусные бейджи + Hc5 облачность ----------
  function cloudLegendHTML(){
    // Простой справочник по покрытиям (общий случай, для ориентира)
    return `
      <details style="display:inline-block;margin-left:8px;">
        <summary style="cursor:pointer;display:inline-block;font-size:12px;opacity:.8">Легенда Hc5</summary>
        <div style="font-size:12px;line-height:1.25;padding:6px 8px;border:1px solid #ccd;border-radius:8px;background:#fff;margin-top:4px;">
          FEW — 1–2 окты (немного)<br/>
          SCT — 3–4 окты (рассеянно)<br/>
          BKN — 5–7 окт (значительная)<br/>
          OVC — 8 окт (сплошная)<br/>
          Высоты: метры над землёй (AGL)
        </div>
      </details>
    `;
  }

  async function renderStatusBadges(stationId){
    try{
      const j = await getJSON(`/status/last?station_id=${encodeURIComponent(stationId)}`);
      const st = (j && j.status) || {};
      const el = document.getElementById(`status-badges-${stationId}`);
      if (!el) return;
      const keys = Object.keys(st);
      const when = j.ts ? new Date(j.ts*1000).toLocaleTimeString() : "—";
      const timeBadge = `<span style="margin-right:8px;opacity:.7;font-size:12px;">${when}</span>`;

      const badgesHtml = keys.map(k => {
        const v = st[k];
        const isErr = k.startsWith("Er");
        const bad = isErr && String(v) !== "0";
        const bg = bad ? "#fdecea" : (isErr ? "#eef" : "#eef");
        const br = bad ? "#f5c2c0" : "#ccd";
        const col = bad ? "#a61b1b" : "#223";
        return `<span title="${STATUS_HINTS[k]||''}" style="padding:2px 6px;border-radius:10px;background:${bg};border:1px solid ${br};color:${col};font-size:12px;">${k}=${v}</span>`;
      }).join(" ");

      let cloudHtml = "";
      if (j && j.cloud) {
        const c = j.cloud;
        const hs = (c.h || []).filter(x => Number(x) > 0).map(x => `${x} м`);
        const label = c.layers ? `${c.layers} сл.` : "—";
        const txt = hs.length ? `${label}: ${hs.join(", ")}` : `${label}`;
        cloudHtml = `<span title="Hc5 — слои и высоты облачности" style="padding:2px 6px;border-radius:10px;background:#eef;border:1px solid #ccd;font-size:12px;">Облачность: ${txt}</span>`;
      }

      const combined = [timeBadge, badgesHtml, cloudHtml, cloudLegendHTML()].filter(Boolean).join(" ");
      el.innerHTML = combined || `<span style="opacity:.6">нет статусов</span>`;
    }catch(e){
      console.error(e);
      const el = document.getElementById(`status-badges-${stationId}`);
      if (el) el.innerHTML = `<span class="series-error">Ошибка загрузки статусов</span>`;
    }
  }

  // ---------- маркеры: подсветка по статусам ----------
  (function injectMarkerCss(){
    if (document.getElementById("station-pin-css")) return;
    const css = `
      .pin { width:14px;height:14px;border-radius:50%;border:2px solid #fff;
             box-shadow:0 0 2px rgba(0,0,0,.5) }
      .pin-green  { background:#2ecc71; }
      .pin-yellow { background:#f1c40f; }
      .pin-red    { background:#e74c3c; }
      .pin-wrap { transform: translate(-7px,-7px); }
    `;
    const st = document.createElement("style"); st.id = "station-pin-css"; st.textContent = css; document.head.appendChild(st);
  })();

  function makeIcon(level="green"){
    const cls = level==="red" ? "pin-red" : level==="yellow" ? "pin-yellow" : "pin-green";
    return L.divIcon({ className: "pin-wrap", html: `<div class="pin ${cls}"></div>`, iconSize: [14,14], iconAnchor: [7,7] });
  }

  function computeSeverity(j){
    if (!j || !j.status) return "green";
    for (const [k,v] of Object.entries(j.status)){
      if (k.startsWith("Er") && String(v) !== "0" && String(v) !== "0.0") return "red";
    }
    for (const [k,v] of Object.entries(j.status)){
      if (k.startsWith("St") && String(v).length) return "yellow";
    }
    return "green";
  }
  function buildStatusTitle(j){
    if (!j) return "нет статуса";
    const t = j.ts ? new Date(j.ts*1000).toLocaleTimeString() : "—";
    const pairs = j.status ? Object.entries(j.status).map(([k,v])=>`${k}=${v}`) : [];
    const cloud = j.cloud ? `; Hc5: ${j.cloud.layers} сл. ${((j.cloud.h||[]).filter(x=>x>0).join(", "))}` : "";
    return `[${t}] ${pairs.join(", ")}${cloud}`;
  }

  const windowOptionsHTML = (selValue) => WINDOW_PRESETS.map(p => `<option value="${p.value}" ${+selValue===p.value?"selected":""}>${p.label}</option>`).join("");

  function updateFetchIndicators(okCount, errCount){
    const total = okCount + errCount;
    if (refreshUI.last && total >= 0){
      refreshUI.last.textContent = `Обновление: ${new Date().toLocaleTimeString()}`;
      refreshUI.last.classList.toggle("ok", errCount === 0);
      refreshUI.last.classList.toggle("err", errCount > 0);
    }
    if (refreshUI.err){
      if (errCount > 0){
        refreshUI.err.style.display = "inline-block";
        refreshUI.err.textContent = `Ошибки: ${errCount}`;
        refreshUI.err.classList.add("err");
      } else {
        refreshUI.err.style.display = "none";
      }
    }
  }

  // ---------- попап ----------
  function popupHTML(st, defaultWindow) {
    const id = st.id || st.code || "unknown";
    const seriesChecks = ["Sa0","Ta1","Hr1","Pa2","Or3","Rt4","Ri4","Ra4","Rs4","Hc5"].map(f=>{
      const title = SERIES_INFO[f] ? `${SERIES_INFO[f]}${UNITS[f] ? `, ед.: ${UNITS[f]}` : ""}` : f;
      return `<label class="chk" title="${title}"><input type="checkbox" class="f" data-f="${f}" checked> ${f}</label>`;
    }).join("");
    return `
      <div class="popup">
        <div class="head">
          <b>Station:</b> ${st.name||"Station"} <span class="muted">${id}</span><br/>
          Lat: ${(+st.lat).toFixed(6)}, Lon: ${(+st.lon).toFixed(6)}
        </div>
        <div class="controls">
          Окно:
          <select class="win">
            ${windowOptionsHTML(defaultWindow)}
          </select>
          &nbsp;&nbsp;Серии:
          ${seriesChecks}
        </div>
        <div id="status-badges-${id}" style="margin:4px 0; display:flex; flex-wrap:wrap; gap:6px;"></div>
        <div class="series-box"></div>
      </div>
    `;
  }

  function wirePopup(pEl, st) {
    const winSel = $(".win", pEl);
    const chks = $all("input.f", pEl);
    const box = $(".series-box", pEl);
    if (winSel) winSel.value = String(currentWindowMinutes);
    const rerender = () => {
      const minutes = parseInt(winSel.value||currentWindowMinutes,10);
      const fields = chks.filter(c=>c.checked).map(c=>c.dataset.f);
      if (!fields.length) { box.innerHTML = `<div class="series-hint">Выберите хотя бы одну серию.</div>`; return; }
      renderSeriesBox(box, st.id||st.code, minutes, fields, "metric");
    };
    winSel.addEventListener("change", rerender);
    chks.forEach(c=> c.addEventListener("change", rerender));
    rerender();

    const _sid = st.id||st.code;
    renderStatusBadges(_sid);
    const _timer = setInterval(() => renderStatusBadges(_sid), 5000);

    // автообновление графиков каждые 10с пока открыт попап
    const _tick = () => {
      const minutes = parseInt(winSel.value||currentWindowMinutes,10);
      const fields = chks.filter(c=>c.checked).map(c=>c.dataset.f);
      if (fields.length) renderSeriesBox(box, _sid, minutes, fields, "metric");
    };
    const _timerCharts = setInterval(_tick, 10000);

    const _root = pEl.closest('.leaflet-popup');
    if (_root) { _root.addEventListener('remove', () => { clearInterval(_timer); clearInterval(_timerCharts); }, { once: true }); }
  }

  // -------------------- map init --------------------
  async function init() {
    refreshUI.last = $("#lastRefresh");
    refreshUI.err = $("#fetchErrors");
    const windowSel = $("#windowSel");
    if (windowSel) {
      currentWindowMinutes = parseInt(windowSel.value || currentWindowMinutes, 10);
      windowSel.addEventListener("change", () => {
        currentWindowMinutes = parseInt(windowSel.value || currentWindowMinutes, 10);
        $all(".win").forEach(sel => { sel.value = String(currentWindowMinutes); sel.dispatchEvent(new Event("change")); });
      });
    }

    const map = L.map("map").setView([59.9, 30.3], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution:"&copy; OpenStreetMap contributors", maxZoom:19 }).addTo(map);

    const list = await getJSON("/stations/list");
    const markers = new Map();

    for (const st of (list.items||[])) {
      const sid = st.id || st.code;
      const m = L.marker([st.lat, st.lon], { icon: makeIcon("green") }).addTo(map);
      markers.set(sid, { marker: m, st });
      m.bindPopup(popupHTML(st, currentWindowMinutes), { maxWidth: 520 });
      m.on("popupopen", e => wirePopup(e.popup.getElement(), st));
    }

    async function refreshMarkerStatuses(){
      let ok = 0, err = 0;
      await runInBatches([...markers.keys()], 5, async (sid) => {
        const obj = markers.get(sid);
        if (!obj) return;
        try {
          const j = await getJSON(`/status/last?station_id=${encodeURIComponent(sid)}`);
          const sev = computeSeverity(j);
          obj.marker.setIcon(makeIcon(sev));
          const title = buildStatusTitle(j);
          const el = obj.marker.getElement();
          if (el) el.title = title;
          ok++;
        } catch (e) {
          console.error(e);
          err++;
        }
      });
      updateFetchIndicators(ok, err);
    }
    await refreshMarkerStatuses();
    setInterval(refreshMarkerStatuses, 10000);

    const btnDemo = $("#btnDemo");
    btnDemo?.addEventListener("click", async () => {
      try { await fetch("/demo/fill", { method:"POST" }); location.reload(); }
      catch { alert("Demo fill failed"); }
    });

    const btnPlace = $("#btnPlace");
    const placeHint = $("#placeHint");
    let placing = false;

    btnPlace?.addEventListener("click", () => {
      placing = true;
      placeHint && (placeHint.style.display = "");
      btnPlace.disabled = true;
      btnPlace.textContent = "Кликните по карте…";
    });

    map.on("click", async (ev) => {
      if (!placing) return;
      placing = false;
      placeHint && (placeHint.style.display = "none");
      btnPlace.disabled = false;
      btnPlace.textContent = "Place station";
      try {
        await postJSON("/stations", { lat: ev.latlng.lat, lon: ev.latlng.lng });
        location.reload();
      } catch (e) {
        console.error(e);
        alert("Ошибка создания станции");
      }
    });
  }

  window.addEventListener("DOMContentLoaded", init);
})();
