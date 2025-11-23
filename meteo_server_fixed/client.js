/* client.js v205 — спарклайны в попапе + корректная постановка станции кликом */

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

  // -------------------- sparkline --------------------
  const COLORS = { Sa0:"#1f77b4", Ta1:"#ff7f0e", Hr1:"#2ca02c", Pa2:"#9467bd" };

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

    if (!ys?.length) { ctx.fillStyle="#888"; ctx.fillText("Нет данных", 10, cssH/2); return; }
    let min=Infinity,max=-Infinity;
    ys.forEach(v=>{ if(v!=null&&!Number.isNaN(v)){ if(v<min)min=v; if(v>max)max=v; }});
    if(!isFinite(min)||!isFinite(max)){ ctx.fillStyle="#888"; ctx.fillText("Нет валидных точек", 10, cssH/2); return; }
    if(min===max){ min-=1; max+=1; }

    const pad=10, W=cssW-pad*2, H=cssH-pad*2;
    ctx.strokeStyle=color; ctx.lineWidth=1.5; ctx.beginPath();
    ys.forEach((v,i)=>{
      const x = pad + (i*W)/Math.max(1,ys.length-1);
      const y = pad + (1-(v-min)/(max-min))*H;
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    });
    ctx.stroke();

    const last = ys[ys.length-1];
    const lx = pad + ((ys.length-1)*W)/Math.max(1,ys.length-1);
    const ly = pad + (1-(last-min)/(max-min))*H;
    ctx.fillStyle=color; ctx.beginPath(); ctx.arc(lx,ly,3,0,Math.PI*2); ctx.fill();

    ctx.fillStyle="#333"; ctx.font="12px system-ui, sans-serif";
    ctx.fillText(`${fmt(last)}${unit?` ${unit}`:""}`, Math.min(cssW-60,lx+6), Math.max(12, ly-6));
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
      const title = document.createElement("div"); title.className="series-title"; title.textContent = f;
      const cv = document.createElement("canvas"); cv.className="series-canvas";
      row.appendChild(title); row.appendChild(cv); el.appendChild(row);

      const unit = f==="Sa0"?"м/с":(f==="Ta1"?"°C":(f==="Hr1"?"%":(f==="Pa2"?"гПа":"")));
      requestAnimationFrame(()=> drawSparkline(cv, data.ts||[], data.series?.[f]||[], COLORS[f]||"#444", unit));
    }
  }

  function popupHTML(st) {
    const id = st.id || st.code || "unknown";
    return `
      <div class="popup">
        <div class="head">
          <b>Station:</b> ${st.name||"Station"} <span class="muted">${id}</span><br/>
          Lat: ${(+st.lat).toFixed(6)}, Lon: ${(+st.lon).toFixed(6)}
        </div>
        <div class="controls">
          Окно (мин):
          <select class="win">
            <option value="60">60</option>
            <option value="120" selected>120</option>
            <option value="180">180</option>
          </select>
          &nbsp;&nbsp;Серии:
          ${["Sa0","Ta1","Hr1","Pa2"].map(f=>`<label class="chk"><input type="checkbox" class="f" data-f="${f}" checked> ${f}</label>`).join("")}
        </div>
        <div class="series-box"></div>
      </div>
    `;
  }
  function wirePopup(pEl, st) {
    const winSel = $(".win", pEl);
    const chks = $all("input.f", pEl);
    const box = $(".series-box", pEl);
    const rerender = () => {
      const minutes = parseInt(winSel.value||"120",10);
      const fields = chks.filter(c=>c.checked).map(c=>c.dataset.f);
      if (!fields.length) { box.innerHTML = `<div class="series-hint">Выберите хотя бы одну серию.</div>`; return; }
      renderSeriesBox(box, st.id||st.code, minutes, fields, "metric");
    };
    winSel.addEventListener("change", rerender);
    chks.forEach(c=> c.addEventListener("change", rerender));
    rerender();
  }

  // -------------------- map init --------------------
  async function init() {
    const map = L.map("map").setView([59.9, 30.3], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution:"&copy; OpenStreetMap contributors", maxZoom:19 }).addTo(map);

    // загрузка станций
    const list = await getJSON("/stations/list");
    for (const st of (list.items||[])) {
      const m = L.marker([st.lat, st.lon]).addTo(map);
      m.bindPopup(popupHTML(st), { maxWidth: 520 });
      m.on("popupopen", e => wirePopup(e.popup.getElement(), st));
    }

    // демо
    const btnDemo = $("#btnDemo");
    btnDemo?.addEventListener("click", async () => {
      try { await fetch("/demo/fill", { method:"POST" }); location.reload(); }
      catch { alert("Demo fill failed"); }
    });

    // постановка станции: кнопка -> режим -> клик по карте
    const btnPlace = $("#btnPlace");
    const placeHint = $("#placeHint");
    let placing = false;

    btnPlace?.addEventListener("click", () => {
      placing = true;
      placeHint.style.display = "";
      btnPlace.disabled = true;
      btnPlace.textContent = "Кликните по карте…";
    });

    map.on("click", async (ev) => {
      if (!placing) return;
      placing = false;
      placeHint.style.display = "none";
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
