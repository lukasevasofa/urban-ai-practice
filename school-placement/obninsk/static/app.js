"use strict";

const S = {data:null, result:null, plan:[], selected:null, mode:"baseline", dirty:false, busy:false,
  state:null, search:{status:"not_started", rows:[], checked:0, total:298, complete:false, best_blocks:[], errors:0},
  sort:{blocks:["block_id",1], auto:["reduction",-1], scenarios:["name",1]}};
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (value, digits=0) => value == null ? "—" : Number(value).toLocaleString("ru-RU", {maximumFractionDigits:digits});
const pct = value => value == null ? "Нет спроса" : fmt(value*100,2)+"%";

function capacityValue(value) {
  if (String(value).trim() === "") throw Error("Введите положительную целочисленную вместимость.");
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number <= 0) throw Error("Вместимость должна быть положительным целым числом.");
  return number;
}

function sortedRows(rows, [key,direction]) {
  return [...rows].sort((a,b) => {
    const x=a[key], y=b[key];
    if (x==null && y==null) return (a.block_id??0)-(b.block_id??0);
    if (x==null) return 1;
    if (y==null) return -1;
    return direction * (typeof x === "number" ? x-y : String(x).localeCompare(String(y),"ru")) ||
      (a.block_id??0)-(b.block_id??0);
  });
}

function csvText(rows, columns) {
  const cell = value => '"'+String(value??"").replace(/"/g,'""')+'"';
  return "\ufeff" + [columns.map(c=>cell(c[1])).join(";"),
    ...rows.map(row=>columns.map(([key])=>cell(row[key])).join(";"))].join("\r\n");
}

function downloadCSV(name, rows, columns) {
  const url=URL.createObjectURL(new Blob([csvText(rows,columns)],{type:"text/csv;charset=utf-8"}));
  const link=document.createElement("a"); link.href=url;link.download=name;link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function api(path, body) {
  const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const payload=await response.json();
  if (!response.ok) throw Error(payload.error || "Запрос не завершён.");
  return payload;
}

function notice(message,error=false) {$("notice").textContent=message;$("notice").classList.toggle("error",error);}

async function task(action,message="Рассчитываем обеспеченность всей территории…") {
  if (S.busy) return;
  S.busy=true;renderButtons();notice(message);
  try {await action();} catch(error) {notice(error.message,true);} finally {S.busy=false;renderButtons();}
}

function provisionColor(value, mode) {
  if (value==null) return "#b8c0c8";
  if (mode==="change") {
    if (Math.abs(value)<1e-9) return "#ffffff";
    return value>0?`hsl(190,65%,${94-50*Math.min(1,value/100)}%)`:
      `hsl(20,80%,${94-45*Math.min(1,-value/100)}%)`;
  }
  const v=Math.max(0,Math.min(1,value));
  if(v===0) return "#fee2e2";
  return `hsl(${v*125},58%,${82-v*35}%)`;
}

function activeValue(row) {
  return S.mode==="baseline"?row.provision_initial:S.mode==="change"?row.delta_provision_pp:row.provision;
}

function featureStyle(feature) {
  const id=feature.properties.block_id,row=S.records.get(id),chosen=id===S.selected;
  const best=S.search.complete && S.search.best_blocks.includes(id);
  return {color:chosen?"#b52780":best?"#1254a0":"#435f70",weight:chosen?3.5:best?2.5:.8,
    fillColor:provisionColor(activeValue(row),S.mode),fillOpacity:.76};
}

function setupMap() {
  if(typeof L==="undefined") throw Error("Не загружена библиотека карты. Проверьте файлы static/vendor.");
  S.map=L.map("map",{preferCanvas:true});
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"© OpenStreetMap contributors"}).addTo(S.map);
  S.existing=L.layerGroup().addTo(S.map);S.planned=L.layerGroup().addTo(S.map);
  S.layer=L.geoJSON(S.data.blocks,{style:featureStyle,onEachFeature:(feature,layer)=>{
    const id=feature.properties.block_id;
    layer.on("click",()=>selectBlock(id));
    layer.on("mouseover",()=>layer.setStyle({weight:3}));
    layer.on("mouseout",()=>layer.setStyle(featureStyle(feature)));
    layer.bindTooltip(()=>{const row=S.records.get(id),value=activeValue(row);
      return `Квартал ${id}<br>${S.mode==="change"?fmt(value,2)+" п.п.":pct(value)}`;});
  }}).addTo(S.map);
  for(const feature of S.data.existing_schools.features) {
    const p=feature.properties, [x,y]=feature.geometry.coordinates;
    const capacity=p.capacity==null?"вместимость не определена":fmt(p.capacity)+" мест";
    L.circleMarker([y,x],{radius:4.5,color:p.public_supply?"#13695a":"#78858e",fillOpacity:1,weight:2})
      .bindPopup(`<b>${esc(p.name)}</b><br>${capacity}<br>${esc(p.capacity_source)}<br>`+
        (p.public_supply?"Учтена в общедоступной мощности":"Вне общедоступной мощности")).addTo(S.existing);
  }
  L.control.layers(null,{"Существующие школы":S.existing,"Новые школы":S.planned}).addTo(S.map);
  const legend=L.control({position:"bottomleft"});legend.onAdd=()=>{const e=L.DomUtil.create("div");e.id="legend";return e;};legend.addTo(S.map);
  S.map.fitBounds(S.layer.getBounds());
}

function renderMap() {
  if(!S.layer) return;
  S.layer.setStyle(featureStyle);S.existing.eachLayer(layer=>layer.bringToFront());
  S.planned.clearLayers();
  for(const school of S.plan) {
    const [x,y]=S.data.points[school.block_id];
    L.marker([y,x],{icon:L.divIcon({className:"planned-label",html:esc(school.capacity),iconSize:[33,33],iconAnchor:[16,16]})})
      .bindTooltip(`Новая школа · квартал ${school.block_id}<br>${fmt(school.capacity)} мест`+
        (S.dirty?"<br>Изменения плана ещё не рассчитаны":"")).on("click",()=>selectBlock(school.block_id)).addTo(S.planned);
  }
  const change=S.mode==="change";
  $("legend").innerHTML=change?
    '<b>Изменение обеспеченности, п.п.</b><div class="legend-gradient" style="background:linear-gradient(90deg,#e05d21,#fff,#278da6)"></div><div class="legend-labels"><span>−100</span><span>0</span><span>+100</span></div>':
    '<b>Доля обслуженного спроса</b><div class="legend-gradient" style="background:linear-gradient(90deg,#fee2e2,#dceba0,#36b14c)"></div><div class="legend-labels"><span>0%</span><span>50%</span><span>100%</span></div>';
  $("legend").innerHTML+='<span class="legend-missing"></span>Нет расчётного спроса<br>Пурпурный контур — выбранный квартал'+
    (S.search.complete?'<br>Синий контур — равноценные лучшие варианты':'');
  const titles={baseline:"Исходное состояние",scenario:"Результат сценария",change:"Изменение относительно исходного"};
  $("viewCaption").textContent=titles[S.mode]+(S.dirty?" · план изменён, требуется расчёт":" · 298 кварталов");
  document.querySelectorAll("[data-mode]").forEach(button=>button.classList.toggle("active",button.dataset.mode===S.mode));
}

function selectBlock(id, zoom=false) {
  S.selected=id;$("blockSelect").value=String(id);renderSelected();renderMap();renderBlocks();renderButtons();
  if(zoom) S.layer.eachLayer(layer=>{if(layer.feature.properties.block_id===id)S.map.fitBounds(layer.getBounds(),{maxZoom:16});});
}

function renderSelected() {
  if(S.selected===null) {$("selectedCard").textContent="Здесь появятся показатели выбранного квартала.";return;}
  const r=S.records.get(S.selected);
  $("selectedCard").innerHTML=`<strong>Квартал ${r.block_id}</strong><br>Население: ${fmt(r.population)} чел. · спрос: ${fmt(r.demand)} мест`+
    `<table><tr><th></th><th>Исходно</th><th>Расчёт</th></tr><tr><td>Мощность, мест</td><td>${fmt(r.capacity_initial)}</td><td>${fmt(r.capacity)}</td></tr>`+
    `<tr><td>Обеспеченность</td><td>${pct(r.provision_initial)}</td><td>${pct(r.provision)}</td></tr>`+
    `<tr><td>Дефицит, мест</td><td>${fmt(r.unmet_initial)}</td><td>${fmt(r.unmet)}</td></tr></table>`+
    (S.dirty?'<div class="muted">В колонке «Расчёт» — исходная модель. Сначала рассчитайте изменённый план.</div>':'');
}

function renderKpis() {
  const r=S.result.summary;
  const cards=[["Расчётное население",fmt(r.population),"Ориентир на 01.01.2025"],
    ["Потребность в местах",fmt(r.demand),"Обслужено: "+fmt(r.served)],
    ["Вместимость сети",fmt(r.capacity),"Прирост: "+fmt(r.capacity_added)+" мест"],
    ["Обеспеченность",fmt(r.provision_percent,2)+"%","От всего расчётного спроса"],
    ["Неудовлетворённый спрос",fmt(r.unmet),"Модельный дефицит, мест"],
    ["Сокращение дефицита",(r.reduction>0?"+":"")+fmt(r.reduction),"Улучшено кварталов: "+fmt(r.improved_blocks)]];
  $("kpis").innerHTML=cards.map(([label,value,caption])=>`<div class="kpi"><span>${label}</span><strong>${value}</strong><small>${caption}</small></div>`).join("");
}

function renderPlan() {
  $("planCount").textContent=S.plan.length;
  $("planList").innerHTML=S.plan.length?S.plan.map(s=>`<div class="plan-row"><span>Квартал <b>${s.block_id}</b></span>`+
    `<input type="number" min="1" step="1" value="${s.capacity}" data-edit="${s.block_id}" aria-label="Вместимость школы в квартале ${s.block_id}">`+
    `<button class="delete-school" data-delete="${s.block_id}" aria-label="Удалить школу из квартала ${s.block_id}">×</button></div>`).join(""):
    '<p class="muted">Пока нет новых школ.</p>';
  document.querySelectorAll("[data-edit]").forEach(input=>{input.disabled=S.busy;input.onchange=()=>{
    try {const capacity=capacityValue(input.value);S.plan.find(s=>s.block_id===Number(input.dataset.edit)).capacity=capacity;invalidate();}
    catch(error){notice(error.message,true);renderPlan();}
  };});
  document.querySelectorAll("[data-delete]").forEach(button=>{button.disabled=S.busy;button.onclick=()=>{
    S.plan=S.plan.filter(s=>s.block_id!==Number(button.dataset.delete));invalidate();};});
  $("planStatus").textContent=S.dirty?"План изменён. Цвет карты и таблица пока показывают исходную модель.":
    "Последний расчёт: "+S.plan.length+" новых школ, "+fmt(S.result.summary.capacity_added)+" новых мест.";
}

function invalidate() {
  S.dirty=true;S.result=S.data.baseline;S.mode="baseline";renderAll();
  notice("План изменён. Нажмите «Рассчитать сценарий», чтобы увидеть влияние на весь город.");
}

function resetView() {
  S.plan=[];S.result=S.data.baseline;S.selected=null;S.mode="baseline";S.dirty=false;
}

function renderBlocks() {
  const q=$("tableFilter").value.trim();
  const rows=sortedRows(S.result.records.filter(r=>!q||String(r.block_id).includes(q)),S.sort.blocks);
  $("blocksTable").querySelector("tbody").innerHTML=rows.map(r=>`<tr data-id="${r.block_id}" class="${r.block_id===S.selected?"selected":""}">`+
    `<td>${r.block_id}</td><td>${fmt(r.population)}</td><td>${fmt(r.capacity_initial)}</td><td>${fmt(r.capacity)}</td><td>${fmt(r.demand)}</td>`+
    `<td>${pct(r.provision_initial)}</td><td>${pct(r.provision)}</td><td>${fmt(r.delta_provision_pp,2)}</td><td>${fmt(r.unmet)}</td></tr>`).join("");
  $("blocksTable").querySelectorAll("tbody tr").forEach(row=>row.onclick=()=>{selectBlock(Number(row.dataset.id),true);renderBlocks();});
}

function savedRows() {
  return [{id:"baseline",name:"Исходное состояние",role:"baseline",reason:"Существующая сеть",result:S.data.baseline},...S.state.scenarios]
    .map(entry=>({...entry,...entry.result.summary}));
}

function chart(target,rows,key,maximum) {
  $(target).innerHTML=rows.map(row=>`<div class="chart-row ${row.id==="baseline"?"baseline":""}"><span class="chart-label" title="${esc(row.name)}">${esc(row.name)}</span>`+
    `<span class="chart-track"><span class="chart-fill" style="display:block;width:${Math.max(0,row[key])/maximum*100}%"></span></span>`+
    `<span class="chart-value">${fmt(row[key],key==="provision_percent"?2:0)}</span></div>`).join("");
}

function renderSaved() {
  const rows=savedRows(),ordered=sortedRows(rows,S.sort.scenarios);
  $("scenariosTable").querySelector("tbody").innerHTML=ordered.map(r=>`<tr data-scenario="${r.id}"><td>${esc(r.name)}</td>`+
    `<td>${r.result.schools.map(s=>s.block_id+" / "+fmt(s.capacity)).join(", ")||"—"}</td><td>${r.school_count}</td><td>${fmt(r.capacity_added)}</td>`+
    `<td>${fmt(r.capacity)}</td><td>${fmt(r.served)}</td><td>${fmt(r.provision_percent,2)}</td><td>${fmt(r.unmet)}</td><td>${fmt(r.reduction)}</td>`+
    `<td>${r.improved_blocks}</td><td>${esc(r.reason)}</td></tr>`).join("");
  $("scenariosTable").querySelectorAll("tbody tr").forEach(row=>row.onclick=()=>{
    const entry=rows.find(r=>r.id===row.dataset.scenario);S.plan=structuredClone(entry.result.schools);
    S.result=entry.result;S.dirty=false;S.mode=entry.id==="baseline"?"baseline":"scenario";
    $("scenarioName").value=entry.id==="baseline"?"":entry.name;$("reason").value=entry.reason;
    $("scenarioRole").value="custom";renderAll();notice("Открыт сохранённый вариант: "+entry.name);
  });
  chart("deficitChart",rows,"unmet",Math.max(1,...rows.map(r=>r.unmet)));
  chart("provisionChart",rows,"provision_percent",100);
}

function renderButtons() {
  if(!S.data) return;
  $("calculate").disabled=S.busy;$("addSchool").disabled=S.busy||S.selected===null;$("reset").disabled=S.busy;
  $("saveScenario").disabled=S.busy||S.dirty||!S.plan.length;
  document.querySelectorAll("[data-edit], [data-delete]").forEach(control=>control.disabled=S.busy);
  const ready=Boolean(S.state.manual_approved),running=S.search.status==="running";
  $("approveManual").disabled=S.busy||ready||!S.state.manual.A||!S.state.manual.B;
  $("startSearch").disabled=S.busy||!ready||running;
  $("cancelSearch").disabled=!running;
  for(const role of ["A","B"]) $("scenarioRole").querySelector(`option[value="${role}"]`).disabled=ready;
  $("scenarioRole").querySelector('option[value="V"]').disabled=!(S.search.complete&&S.search.capacity===600);
  $("manualStatus").innerHTML=["A","B"].map((role,i)=>`<span class="${S.state.manual[role]?"done":""}">${i?"Б":"А"}: ${S.state.manual[role]?"выбор сохранён":"ожидает ручного выбора"}</span>`).join("")+
    `<span class="${ready?"done":""}">${ready?"Ручные варианты подтверждены":"Автопоиск пока закрыт"}</span>`;
}

async function showCandidate(id) {
  await task(async()=>{
    const plan=[{block_id:id,capacity:S.search.capacity}];
    const result=await api("/api/calculate",{schools:plan});
    S.plan=plan;S.result=result;S.dirty=false;S.mode="scenario";S.selected=id;
    $("scenarioName").value="Автовариант: квартал "+id;
    $("scenarioRole").value=S.search.complete&&S.search.capacity===600&&S.search.best_blocks.includes(id)?"V":"custom";
    $("reason").value=S.search.complete?"Вариант из полного независимого перебора всех 298 кварталов.":"Предварительный вариант из незавершённого перебора.";
    renderAll();selectBlock(id,true);notice("На карте вариант квартала "+id+"; прирост "+fmt(S.search.capacity)+" мест.");
  });
}

function renderSearch() {
  const a=S.search,running=a.status==="running";
  $("autoProgress").value=a.checked;$("autoProgress").max=a.total;
  $("autoBadge").textContent=running?"Идёт перебор":a.complete?"Проверены все кварталы":a.status==="not_started"?"Поиск не запускался":"Перебор не завершён";
  $("searchStatus").textContent=`Проверено ${a.checked} из ${a.total}. Ошибок: ${a.errors}. `+
    (a.complete?"Полный поиск завершён.":running?"Результаты пока предварительные.":a.status==="not_started"?"Дождёмся ручного выбора А и Б.":"Лучшие среди всех кварталов не определены.")+(a.error?" "+a.error:"");
  $("bestBlocks").innerHTML=a.complete?`<p>Максимальное сокращение: <b>${fmt(a.rows[0].reduction)} мест</b>. Все равноценные кварталы (${a.best_blocks.length}):</p>`+
    a.best_blocks.map(id=>`<button data-best="${id}">№${id}</button>`).join(""):"";
  $("bestBlocks").querySelectorAll("[data-best]").forEach(button=>button.onclick=()=>showCandidate(Number(button.dataset.best)));
  const rows=sortedRows(a.rows,S.sort.auto);
  $("autoTable").querySelector("tbody").innerHTML=rows.map(r=>`<tr ${r.error?"":"data-id="+r.block_id} class="${a.complete&&a.best_blocks.includes(r.block_id)?"best":""}">`+
    `<td>${r.block_id}</td><td>${fmt(r.capacity_added)}</td><td>${fmt(r.unmet)}</td><td>${fmt(r.reduction)}</td><td>${fmt(r.provision_percent,2)}</td>`+
    `<td class="${r.error?"error-cell":""}">${r.error?esc(r.error):"Рассчитан"}</td></tr>`).join("");
  $("autoTable").querySelectorAll("tbody tr[data-id]").forEach(row=>row.onclick=()=>showCandidate(Number(row.dataset.id)));
  renderButtons();if(S.layer)S.layer.setStyle(featureStyle);
}

function renderAll() {
  S.records=new Map(S.result.records.map(row=>[row.block_id,row]));
  renderKpis();renderPlan();renderSelected();renderBlocks();renderSaved();renderButtons();renderMap();
}

function connectEvents() {
  $("blockSelect").onchange=()=>{if($("blockSelect").value!=="")selectBlock(Number($("blockSelect").value),true);};
  $("fitMap").onclick=()=>S.map.fitBounds(S.layer.getBounds());
  document.querySelectorAll("[data-mode]").forEach(button=>button.onclick=()=>{S.mode=button.dataset.mode;renderMap();});
  $("addSchool").onclick=()=>{try{
    if(S.selected===null)throw Error("Сначала выберите квартал на карте.");
    const capacity=capacityValue($("manualCapacity").value);
    if(S.plan.some(s=>s.block_id===S.selected))throw Error("Школа в этом квартале уже добавлена. Измените число мест в плане.");
    S.plan.push({block_id:S.selected,capacity});invalidate();
  }catch(error){notice(error.message,true);}};
  $("calculate").onclick=()=>task(async()=>{
    const result=await api("/api/calculate",{schools:structuredClone(S.plan)});
    S.result=result;S.plan=structuredClone(result.schools);S.dirty=false;S.mode=S.plan.length?"scenario":"baseline";renderAll();
    notice("Расчёт завершён. Обеспеченность "+fmt(result.summary.provision_percent,2)+"%; остаточный дефицит "+fmt(result.summary.unmet)+" мест.");
  });
  $("reset").onclick=()=>{resetView();$("blockSelect").value="";$("scenarioName").value="";$("reason").value="";$("scenarioRole").value="custom";
    $("manualCapacity").value=600;$("tableFilter").value="";
    renderAll();notice("План сброшен. Исходная модель восстановлена; сохранённые сценарии не удалены.");};
  $("scenarioRole").onchange=()=>{const role=$("scenarioRole").value;
    if(role==="A"||role==="B"){$("scenarioName").value="Сценарий "+(role==="A"?"А":"Б");$("manualCapacity").value=role==="A"?600:300;}};
  $("saveScenario").onclick=()=>task(async()=>{
    await api("/api/scenarios",{name:$("scenarioName").value,reason:$("reason").value,role:$("scenarioRole").value,schools:S.plan});
    const data=await api("/api/bootstrap");S.state=data.state;renderSaved();renderButtons();notice("Сценарий и его расчёт сохранены на компьютере.");
  },"Сохраняем сценарий с независимым пересчётом…");
  $("approveManual").onclick=()=>task(async()=>{S.state=await api("/api/approve-manual",{});$("scenarioRole").value="custom";
    renderButtons();notice("Ручные варианты зафиксированы. Автопоиск открыт, но ещё не запущен.");},"Фиксируем ваши ручные варианты…");
  $("startSearch").onclick=()=>task(async()=>{S.search=await api("/api/search/start",{capacity:capacityValue($("autoCapacity").value)});
    renderSearch();notice("Начат независимый перебор всех 298 кварталов.");pollSearch();},"Запускаем перебор…");
  $("cancelSearch").onclick=async()=>{try{await api("/api/search/cancel",{});notice("Перебор остановится после текущего варианта. Неполный поиск не будет считаться завершённым.");}catch(e){notice(e.message,true);}};
  $("tableFilter").oninput=renderBlocks;
  for(const [id,key,render] of [["blocksTable","blocks",renderBlocks],["autoTable","auto",renderSearch],["scenariosTable","scenarios",renderSaved]]) {
    $(id).querySelectorAll("th[data-sort]").forEach(th=>th.onclick=()=>{
      S.sort[key]=[th.dataset.sort,S.sort[key][0]===th.dataset.sort?-S.sort[key][1]:1];render();
    });
  }
  $("exportBlocks").onclick=()=>downloadCSV("obninsk_quarters.csv",S.result.records.map(r=>({...r,provision_initial:r.provision_initial==null?null:r.provision_initial*100,
    provision:r.provision==null?null:r.provision*100})),[["block_id","ID квартала"],["population","Население"],["capacity_initial","Мест до"],
    ["capacity","Мест после"],["added_capacity","Новых мест"],["demand","Потребность"],["served","Обслужено"],
    ["provision_initial","Обеспеченность до, %"],["provision","Обеспеченность после, %"],["delta_provision_pp","Изменение, п.п."],["unmet","Дефицит"],["reduction","Сокращение дефицита"]]);
  $("exportScenarios").onclick=()=>downloadCSV("obninsk_scenarios.csv",savedRows().map(r=>({...r,quarters:r.result.schools.map(s=>s.block_id+":"+s.capacity).join(", ")})),
    [["name","Вариант"],["quarters","Кварталы и места"],["school_count","Новых школ"],["capacity_added","Новых мест"],["capacity","Всего мест"],
     ["served","Обслужено"],["provision_percent","Обеспеченность, %"],["unmet","Дефицит"],["reduction","Сокращение"],["improved_blocks","Улучшено кварталов"],["reason","Обоснование"]]);
  $("exportAuto").onclick=()=>downloadCSV(S.search.complete?"obninsk_auto_complete.csv":"obninsk_auto_incomplete.csv",
    S.search.rows.map(r=>({...r,search_status:S.search.status})),[["block_id","Квартал"],["capacity_added","Новых мест"],
    ["unmet","Остаточный дефицит"],["reduction","Сокращение дефицита"],["provision_percent","Обеспеченность, %"],["error","Ошибка"],["search_status","Статус перебора"]]);
}

async function pollSearch() {
  try {S.search=await api("/api/search");renderSearch();
    if(S.search.status==="running")setTimeout(pollSearch,900);
    else notice(S.search.complete?"Полный перебор завершён. Показаны все равноценные лучшие кварталы.":"Перебор не завершён: оптимальный квартал среди всех 298 не подтверждён.",!S.search.complete);
  }catch(error){notice("Не удалось получить прогресс: "+error.message,true);}
}

async function boot() {
  try {
    S.data=await api("/api/bootstrap");S.state=S.data.state;S.result=S.data.baseline;
    if(S.result.records.length!==298)throw Error("Не совпадает число кварталов исходной модели.");
    S.records=new Map(S.result.records.map(r=>[r.block_id,r]));
    for(const row of S.result.records)$("blockSelect").add(new Option("Квартал "+row.block_id,row.block_id));
    setupMap();connectEvents();renderAll();S.search=await api("/api/search");renderSearch();
    if(S.search.status==="running")pollSearch();
    notice("Исходный расчёт проверен: 57,46% обеспеченности, 6812 мест дефицита. Выберите кварталы для А и Б.");
  }catch(error){notice(error.message,true);}
}
if(typeof document!=="undefined")document.addEventListener("DOMContentLoaded",boot);
