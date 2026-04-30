/* app.js - Fillzy: Auth + Mapbox integration + robust fallback mock + diagnostics */
(() => {
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from((ctx || document).querySelectorAll(sel));

  // ---------------- CONFIG ----------------
  // Pega aquí tu token Mapbox (sin comillas extras). Si lo dejas vacío, usa fallback mock.
  const MAPBOX_TOKEN = 'pk.eyJ1IjoiYWFhbGV4dHVyaW5nIiwiYSI6ImNtZTgyMzhsZzBhdHEybHByMDhpeDEyY24ifQ.Tq4FvLklPvSzm2SCXRK-nw';
  const MAP_STYLE = [
    { elementType: "geometry", stylers: [{ color: "#242f3e" }] },
    { elementType: "labels.text.stroke", stylers: [{ color: "#242f3e" }] },
    { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
    { featureType: "administrative.locality", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
    { featureType: "poi", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
    { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#263c3f" }] },
    { featureType: "poi.park", elementType: "labels.text.fill", stylers: [{ color: "#6b9a76" }] },
    { featureType: "road", elementType: "geometry", stylers: [{ color: "#38414e" }] },
    { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#212a37" }] },
    { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#9ca5b3" }] },
    { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#746855" }] },
    { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#1f2835" }] },
    { featureType: "road.highway", elementType: "labels.text.fill", stylers: [{ color: "#f3d19c" }] },
    { featureType: "transit", elementType: "geometry", stylers: [{ color: "#2f3948" }] },
    { featureType: "transit.station", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: "#17263c" }] },
    { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#515c6d" }] },
    { featureType: "water", elementType: "labels.text.stroke", stylers: [{ color: "#17263c" }] }
  ];
  // ----------------------------------------

  const MAP_BOUNDS = { latMin: 19.0, latMax: 19.6, lngMin: -99.4, lngMax: -98.8 };
  const DEFAULT_STATIONS = [
    { id: 's1', name: 'Shell Reforma', lat: 19.430, lng: -99.140, color: '#ff6b6b', capacity: 6, availability:{slotsFree:3} },
    { id: 's2', name: 'Gulf Centro', lat: 19.419, lng: -99.150, color: '#6b9bff', capacity: 4, availability:{slotsFree:2} },
    { id: 's3', name: 'BP Norte', lat: 19.480, lng: -99.120, color: '#a1ff6b', capacity: 3, availability:{slotsFree:1} }
  ];

  // Estado
  let mapInstance = null;
  let markersMap = {};
  let delegatedHandlerInstalled = false;
  let googleMapInstance = null;

  // Agregar después de la declaración de variables globales:
  let draggedColor = null;
  let previewElement = null;
  let selectedLocation = null;
  let tempMarker = null;

  // Añadir después de las variables globales
  let draggedStation = null;
  let draggedStationCard = null;

  /** Vacío = mismo origen (sirve Fillzy desde el server en :3041). Override: window.__POE_API_BASE__ = 'http://127.0.0.1:3041' */
  const POE_API_BASE =
    typeof window !== "undefined" && window.__POE_API_BASE__ !== undefined
      ? String(window.__POE_API_BASE__).replace(/\/$/, "")
      : "";

  let powerERoutePolyline = null;
  let powerEStepMarkers = [];

  // ---- util: banner + console ----
  function setStatus(text, visible = true, warn = false) {
    const el = document.getElementById('mapStatus');
    if (el) {
      el.textContent = text;
      el.style.display = visible ? 'block' : 'none';
      el.style.background = warn ? 'linear-gradient(90deg, rgba(180,60,60,0.9), rgba(100,30,30,0.85))' : 'rgba(0,0,0,0.6)';
    }
    if (warn) console.warn('Fillzy status:', text);
    else console.log('Fillzy status:', text);
  }

  // ---- storage robusto ----
  function loadStations(){
    try {
      const s = localStorage.getItem('fillzy_stations');
      if (!s) { localStorage.setItem('fillzy_stations', JSON.stringify(DEFAULT_STATIONS)); return DEFAULT_STATIONS.slice(); }
      const parsed = JSON.parse(s);
      if (!Array.isArray(parsed)) throw new Error('not-array');
      return parsed;
    } catch (e) {
      console.warn('fillzy: stations corrupto, reseteando', e);
      localStorage.setItem('fillzy_stations', JSON.stringify(DEFAULT_STATIONS));
      return DEFAULT_STATIONS.slice();
    }
  }
  function saveStations(list){ try { localStorage.setItem('fillzy_stations', JSON.stringify(list)); } catch(e){ console.error(e); } }

  // ---- auth mock ----
  function loginUser(username){ const role = (username && username.toLowerCase()==='admin') ? 'admin' : 'user'; const u = { username, role }; localStorage.setItem('fillzy_user', JSON.stringify(u)); return u; }
  function logout(){ localStorage.removeItem('fillzy_user'); location.href = 'index.html'; }
  function getUser(){ try { return JSON.parse(localStorage.getItem('fillzy_user')||'null'); } catch(e){ return null; } }

  // ---- calc pos fallback ----
  function latLngToPos(lat, lng, container){
    const rect = container.getBoundingClientRect();
    const x = ((lng - MAP_BOUNDS.lngMin) / (MAP_BOUNDS.lngMax - MAP_BOUNDS.lngMin)) * rect.width;
    const y = (1 - (((lat - MAP_BOUNDS.latMin) / (MAP_BOUNDS.latMax - MAP_BOUNDS.latMin)))) * rect.height;
    return { x, y };
  }

  // ---- cargar Mapbox script dinámico ----
  function loadMapboxScript() {
    return new Promise((resolve, reject) => {
      if (typeof mapboxgl !== 'undefined') return resolve();
      const src = 'https://api.mapbox.com/mapbox-gl-js/v2.16.1/mapbox-gl.js';
      const s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = () => { console.log('Mapbox script loaded'); resolve(); };
      s.onerror = (e) => reject(new Error('No se pudo cargar el script Mapbox: ' + src));
      document.head.appendChild(s);
    });
  }

  function createGoogleStationMarker(station) {
    if (!googleMapInstance) return null;
    const marker = new google.maps.Marker({
      position: { lat: station.lat, lng: station.lng },
      map: googleMapInstance,
      title: station.name || "Estación",
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: station.color || "#6b9bff",
        fillOpacity: 1,
        strokeWeight: 2,
        strokeColor: "#ffffff",
        scale: 10,
      },
      animation: google.maps.Animation.DROP,
    });
    marker.addListener("click", () => {
      const infowindow = new google.maps.InfoWindow({
        content: `<div style="color:black;padding:8px">
                        <strong>${station.name || "Punto"}</strong><br>
                        Slots libres: ${station.availability?.slotsFree ?? "—"}<br>
                        Capacidad: ${station.capacity ?? "—"}
                    </div>`,
      });
      infowindow.open(googleMapInstance, marker);
    });
    return marker;
  }

  function refreshGoogleMarkers(stations) {
    if (!googleMapInstance) return;
    Object.keys(markersMap).forEach((id) => {
      try {
        const mk = markersMap[id];
        if (mk && mk.setMap) mk.setMap(null);
      } catch (e) {}
    });
    markersMap = {};
    stations.forEach((station) => {
      markersMap[station.id] = createGoogleStationMarker(station);
    });
  }

  function clearPowerERouteOverlay() {
    if (powerERoutePolyline) {
      powerERoutePolyline.setMap(null);
      powerERoutePolyline = null;
    }
    powerEStepMarkers.forEach((m) => {
      try {
        m.setMap(null);
      } catch (e) {}
    });
    powerEStepMarkers = [];
  }

  function updatePowerEPanel(data) {
    const panel = document.getElementById("powerEPanel");
    if (!panel) return;
    panel.hidden = false;
    panel.innerHTML = `
      <div class="power-e-panel__title">Ruta Power E (POC)</div>
      <div class="power-e-panel__row"><span>Trayecto</span><strong>${data.origin} → ${data.destination}</strong></div>
      <div class="power-e-panel__row"><span>Distancia</span><strong>${data.distance_km} km</strong></div>
      <div class="power-e-panel__row"><span>Tiempo</span><strong>${data.estimated_time_label}</strong></div>
      <div class="power-e-panel__row"><span>Ahorro combustible</span><strong>${data.savings?.fuel_percent_vs_baseline ?? "—"}</strong></div>
      <div class="power-e-panel__row"><span>CO₂ (aprox.)</span><strong>${data.savings?.co2_reduced_kg ?? "—"} kg</strong></div>
      <button type="button" class="power-e-panel__btn" id="powerERefreshBtn">Actualizar ruta</button>
    `;
    document.getElementById("powerERefreshBtn")?.addEventListener("click", () => {
      fetchAndDrawPowerERoute();
    });
  }

  function renderPowerERouteOnMap(data) {
    if (!googleMapInstance || !data.optimized_steps?.length) return;
    const path = data.optimized_steps.map((s) => ({
      lat: Number(s.lat),
      lng: Number(s.lng),
    }));
    powerERoutePolyline = new google.maps.Polyline({
      path,
      geodesic: true,
      strokeColor: "#3ECF8E",
      strokeOpacity: 0.92,
      strokeWeight: 5,
      map: googleMapInstance,
    });
    const bounds = new google.maps.LatLngBounds();
    path.forEach((p) => bounds.extend(p));
    googleMapInstance.fitBounds(bounds, { top: 72, right: 40, bottom: 72, left: 300 });

    data.optimized_steps.forEach((step, i) => {
      const marker = new google.maps.Marker({
        position: { lat: Number(step.lat), lng: Number(step.lng) },
        map: googleMapInstance,
        title: step.label || `Paso ${i + 1}`,
        label: {
          text: String(step.order ?? i + 1),
          color: "#0c1015",
          fontSize: "11px",
          fontWeight: "700",
        },
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: "#3d9cf0",
          fillOpacity: 1,
          strokeWeight: 2,
          strokeColor: "#ffffff",
          scale: 12,
        },
        zIndex: (google.maps.Marker.MAX_ZINDEX || 1000000) + 20,
      });
      const html = `<div style="color:#111;padding:8px 10px;max-width:280px;font-family:system-ui,sans-serif">
          <strong>${step.label || "Paso"}</strong><br/>
          <span style="font-size:13px;color:#333">${step.advice?.headline || ""}</span><br/>
          <span style="font-size:12px;color:#555;line-height:1.35">${step.advice?.detail || ""}</span>
        </div>`;
      marker.addListener("click", () => {
        const iw = new google.maps.InfoWindow({ content: html });
        iw.open(googleMapInstance, marker);
      });
      powerEStepMarkers.push(marker);
    });
  }

  async function fetchAndDrawPowerERoute() {
    if (!googleMapInstance) return;
    const url = `${POE_API_BASE}/api/route-optimization`;
    try {
      setStatus("Cargando ruta Power E…", true, false);
      const res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      clearPowerERouteOverlay();
      renderPowerERouteOnMap(data);
      updatePowerEPanel(data);
      setStatus(
        `Ruta Power E: ${data.distance_km} km · ahorro ${data.savings?.fuel_percent_vs_baseline || ""}`,
        true,
        false
      );
      setTimeout(() => setStatus("", false), 4500);
    } catch (e) {
      console.warn("Power E POC:", e);
      setStatus(
        "No se pudo cargar /api (usa el dashboard desde el server en :3041)",
        true,
        true
      );
    }
  }

  // -------------------------------- MAP / MARKERS --------------------------------
  async function initMapAndMarkers(stations) {
    const mapContainer = document.getElementById('map');
    if (!mapContainer) { 
        setStatus('Contenedor #map no encontrado', true, true); 
        return; 
    }

    try {
        googleMapInstance = new google.maps.Map(mapContainer, {
            center: { lat: stations[0]?.lat ?? 19.4326, lng: stations[0]?.lng ?? -99.1332 },
            zoom: 12,
            styles: MAP_STYLE,
            disableDefaultUI: true,
            zoomControl: false,
            gestureHandling: 'greedy',
            backgroundColor: '#0c1015'
        });

        // Esperar a que el mapa esté completamente cargado
        await new Promise(resolve => {
            google.maps.event.addListenerOnce(googleMapInstance, 'tilesloaded', () => {
                setTimeout(resolve, 500); // Dar tiempo extra para que la proyección esté lista
            });
        });

        // Controladores de zoom
        document.getElementById('zoomIn')?.addEventListener('click', () => {
            googleMapInstance.setZoom(googleMapInstance.getZoom() + 1);
        });
        document.getElementById('zoomOut')?.addEventListener('click', () => {
            googleMapInstance.setZoom(googleMapInstance.getZoom() - 1);
        });

        // Permitir arrastrar al mapa
        mapContainer.style.cursor = 'grab';
        mapContainer.addEventListener('mousedown', () => { mapContainer.style.cursor = 'grabbing'; });
        mapContainer.addEventListener('mouseup', () => { mapContainer.style.cursor = 'grab'; });

        // Añadir marcadores existentes
        stations.forEach((station) => {
          markersMap[station.id] = createGoogleStationMarker(station);
        });

        // Habilitar drag & drop en el mapa
        mapContainer.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });

        mapContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            if (!draggedColor) return;

            const bounds = mapContainer.getBoundingClientRect();
            const point = new google.maps.Point(
                e.clientX - bounds.left,
                e.clientY - bounds.top
            );

            // Convertir punto a coordenadas
            const latLng = googleMapInstance.getProjection().fromContainerPixelToLatLng(point);
            const tempStation = {
                lat: latLng.lat(),
                lng: latLng.lng(),
                name: 'Nueva estación',
                color: draggedColor
            };

            // Añadir marcador temporal
            createGoogleStationMarker(tempStation);
            draggedColor = null;
        });

        // Esperar a que el mapa esté listo
        await new Promise(resolve => googleMapInstance.addListener('idle', resolve));
        
        // Inicializar el drag & drop después de que el mapa esté listo
        initDragAndDrop();

        await fetchAndDrawPowerERoute();
    } catch (err) {
        console.error('Error al inicializar el mapa:', err);
        setStatus('Error al cargar el mapa', true, true);
    }
  }

  function refreshMapboxMarkers(stations){
    Object.keys(markersMap).forEach(id => {
      try { const mk = markersMap[id]; if (mk && mk.remove) mk.remove(); } catch(e){}
    });
    markersMap = {};
    stations.forEach(s => createMapboxMarker(s));
  }

  function createMapboxMarker(s){
    if (!mapInstance) return;
    const el = document.createElement('div');
    el.className = 'marker mapbox-marker';
    el.style.width = '16px';
    el.style.height = '16px';
    el.style.borderRadius = '50%';
    el.style.background = s.color;
    el.style.border = '2px solid rgba(0,0,0,0.45)';
    el.style.boxShadow = '0 6px 14px rgba(0,0,0,0.6)';
    el.style.transform = 'translate(-50%,-50%)';

    const popupHtml = `
      <div style="min-width:220px">
        <div style="font-weight:700;margin-bottom:6px">${s.name}</div>
        <div style="color:var(--muted);font-size:0.9rem">${s.availability?.slotsFree ?? '?'} slots libres • Cap: ${s.capacity}</div>
        <div style="margin-top:8px;display:flex;gap:8px;justify-content:flex-end">
          <button class="btn ghost small view-btn" data-id="${s.id}">Detalles</button>
          <button class="btn primary small reserve-btn" data-id="${s.id}">Reservar</button>
        </div>
      </div>
    `;
    const popup = new mapboxgl.Popup({ offset: 25, closeOnClick: true }).setHTML(popupHtml);
    const marker = new mapboxgl.Marker({ element: el }).setLngLat([s.lng, s.lat]).setPopup(popup).addTo(mapInstance);
    markersMap[s.id] = marker;
  }

  // fallback mock
  function renderMapFallback(stations){
    const map = $('#map');
    if(!map) { setStatus('Contenedor #map no encontrado (fallback)', true, true); return; }

    try { map.innerHTML = ''; } catch(e){ console.error(e); }

    const rect = map.getBoundingClientRect();
    const tries = map._fillzy_render_tries || 0;
    if ((rect.width === 0 || rect.height === 0) && tries < 12) {
      map._fillzy_render_tries = tries + 1;
      setTimeout(()=> renderMapFallback(stations), 120);
      return;
    }
    map._fillzy_render_tries = 0;

    const bg = document.createElement('div'); bg.style.position='absolute'; bg.style.inset='0'; bg.style.pointerEvents='none'; map.appendChild(bg);

    markersMap = {};
    stations.forEach(s => {
      const m = document.createElement('div'); m.className = 'marker';
      m.style.background = s.color;
      m.dataset.id = s.id;
      const pulse = document.createElement('div'); pulse.className='pulse'; pulse.style.background = s.color;
      m.appendChild(pulse);
      const pos = latLngToPos(s.lat, s.lng, map);
      if (!isFinite(pos.x) || !isFinite(pos.y)) { m.style.left = '10px'; m.style.top = '10px'; }
      else { m.style.left = pos.x + 'px'; m.style.top = pos.y + 'px'; }
      m.addEventListener('click', (ev) => { ev.stopPropagation(); showPopoverForStation(s, pos, map); });
      map.appendChild(m);
      markersMap[s.id] = m;
    });

    const handler = () => { const p = $('.map-popover'); if(p) p.remove(); };
    map.addEventListener('click', handler);
    map._fillzy_clickHandler = handler;

    setStatus('Mapa mock activo (fallback)', false);
  }

  function showPopoverForStation(station, pos, map){
    $$('.map-popover').forEach(n=>n.remove());
    const pop = document.createElement('div');
    pop.className = 'map-popover';
    pop.style.position='absolute';
    pop.style.left = (pos.x + 12) + 'px';
    pop.style.top = (pos.y - 6) + 'px';
    pop.style.background = 'rgba(10,10,10,0.95)';
    pop.style.border = '1px solid rgba(255,255,255,0.04)';
    pop.style.padding = '10px';
    pop.style.borderRadius = '10px';
    pop.style.minWidth = '200px';
    pop.style.color = 'var(--text)';
    pop.innerHTML = `<div style="font-weight:700">${station.name}</div>
      <div style="color:var(--muted);font-size:0.9rem">${station.availability?.slotsFree ?? '?'} slots libres • Cap: ${station.capacity}</div>
      <div style="margin-top:8px;display:flex;gap:8px;justify-content:flex-end">
        <button class="btn ghost small view-btn" data-id="${station.id}">Detalles</button>
        <button class="btn primary small reserve-btn" data-id="${station.id}">Reservar</button>
      </div>`;
    map.appendChild(pop);
    installPopupDelegation();
  }

  function panToStation(station){
    if (mapInstance) {
      try { mapInstance.flyTo({ center: [station.lng, station.lat], zoom: 15, essential: true }); } catch(e){ console.warn(e); }
      const mk = markersMap[station.id];
      if (mk && mk.getElement) {
        mk.getElement().animate([{ transform:'translate(-50%,-50%) scale(1)' }, { transform:'translate(-50%,-50%) scale(1.6)' }, { transform:'translate(-50%,-50%) scale(1)' }], { duration:700 });
      }
    } else {
      const mk = markersMap[station.id];
      if (mk) mk.animate([{ transform: 'translate(-50%,-50%) scale(1)' }, { transform: 'translate(-50%,-50%) scale(1.6)' }, { transform: 'translate(-50%,-50%) scale(1)' }], { duration:700 });
    }
  }

  // Delegación para botones dentro de popups
  function installPopupDelegation(){
    if (delegatedHandlerInstalled) return;
    delegatedHandlerInstalled = true;
    document.addEventListener('click', (ev) => {
      const reserve = ev.target.closest && ev.target.closest('.reserve-btn');
      if (reserve) {
        ev.preventDefault();
        const id = reserve.dataset.id;
        handleReserveById(id);
        return;
      }
      const view = ev.target.closest && ev.target.closest('.view-btn');
      if (view) {
        ev.preventDefault();
        const id = view.dataset.id;
        const stations = loadStations();
        const s = stations.find(x=>x.id===id);
        if (s) panToStation(s);
        return;
      }
    });
  }

  function handleReserveById(stationId){
    const stations = loadStations();
    const s = stations.find(x=>x.id === stationId);
    if (!s) return alert('Estación no encontrada');
    if (!s.availability) s.availability = { slotsFree: 0 };
    if ((s.availability.slotsFree || 0) <= 0) return alert('No hay slots disponibles.');
    s.availability.slotsFree = Math.max(0, (s.availability.slotsFree || 0) - 1);
    saveStations(stations);
    updateStats(stations);
    renderStationList(stations);
    refreshGoogleMarkers(stations); // Usar refreshGoogleMarkers en lugar de refreshMapboxMarkers
    alert('Reserva simulada creada (demo).');
  }

  // ---- Header / list / stats ----
  function renderHeaderForUser(){
    const header = $('#header-actions');
    if(!header) return;
    const user = getUser();
    header.innerHTML = '';
    if(!user){ header.innerHTML = `<a class="btn ghost" href="login.html">Inicia Sesión</a><a class="btn primary" href="register.html">Regístrate</a>`; return; }
    const avatarBtn = document.createElement('button'); avatarBtn.className='btn ghost'; avatarBtn.textContent = user.username;
    const logoutBtn = document.createElement('button'); logoutBtn.className='btn ghost'; logoutBtn.textContent = 'Salir'; logoutBtn.onclick = logout;
    header.appendChild(avatarBtn);
    if (user.role === 'admin') {
      const add = document.createElement('button'); add.className='btn primary'; add.textContent='Agregar estación'; add.onclick = openAddPanel;
      header.appendChild(add);
    }
    header.appendChild(logoutBtn);
  }

  function updateStats(stations){
    $('#stat-stations') && ($('#stat-stations').textContent = stations.length);
    const free = stations.reduce((s,st)=> s + (st.availability?.slotsFree || 0), 0);
    $('#stat-free') && ($('#stat-free').textContent = free);
    $('#stat-res') && ($('#stat-res').textContent = Math.max(0, Math.floor(stations.length * 0.6)));
  }

  function renderStationList(stations) {
    const list = $('#stationList'); 
    if(!list) return;
    const user = getUser();
    const isAdmin = user?.role === 'admin';

    list.innerHTML = '';
    
    // Agregar trash bin para admins
    if (isAdmin) {
      const trashBin = document.createElement('div');
      trashBin.className = 'trash-bin';
      trashBin.innerHTML = '<i class="fas fa-trash"></i><span>Arrastra aquí para eliminar</span>';

      let scrollInterval = null;
      
      function checkScroll(e) {
        const listRect = list.getBoundingClientRect();
        const threshold = 150; // Zona de scroll más amplia
        
        function getScrollSpeed(distance) {
          // Convertir distancia en velocidad (más cerca = más rápido)
          const maxSpeed = 15; // Velocidad máxima de scroll
          const speed = Math.pow(1 - (distance / threshold), 2) * maxSpeed;
          return Math.ceil(speed);
        }

        if (e.clientY > (listRect.bottom - threshold)) {
          // Scroll hacia abajo
          const distance = listRect.bottom - e.clientY;
          const speed = getScrollSpeed(distance);
          
          if (!scrollInterval) {
            scrollInterval = setInterval(() => {
              list.scrollTop += speed;
            }, 16);
          }
        } else if (e.clientY < (listRect.top + threshold)) {
          // Scroll hacia arriba
          const distance = e.clientY - listRect.top;
          const speed = getScrollSpeed(distance);
          
          if (!scrollInterval) {
            scrollInterval = setInterval(() => {
              list.scrollTop -= speed;
            }, 16);
          }
        } else {
          // Fuera de la zona de scroll
          if (scrollInterval) {
            clearInterval(scrollInterval);
            scrollInterval = null;
          }
        }
      }

      list.addEventListener('dragover', checkScroll);
      list.addEventListener('dragleave', () => {
        if (scrollInterval) {
          clearInterval(scrollInterval);
          scrollInterval = null;
        }
      });
      list.addEventListener('drop', () => {
        if (scrollInterval) {
          clearInterval(scrollInterval);
          scrollInterval = null;
        }
      });

      trashBin.addEventListener('dragover', e => {
        e.preventDefault();
        trashBin.classList.add('drag-over');
      });

      trashBin.addEventListener('dragleave', () => {
        trashBin.classList.remove('drag-over');
      });
      trashBin.addEventListener('drop', e => {
        e.preventDefault();
        trashBin.classList.remove('drag-over');
        if (draggedStation && confirm('¿Estás seguro de eliminar esta estación?')) {
          const stations = loadStations().filter(s => s.id !== draggedStation);
          saveStations(stations);
          draggedStationCard?.classList.add('deleting');
          setTimeout(() => {
            updateStats(stations);
            renderStationList(stations);
            refreshGoogleMarkers(stations);
          }, 300);
        }
        // Limpiar el intervalo de scroll si existe
        if (scrollInterval) {
          clearInterval(scrollInterval);
          scrollInterval = null;
        }
      });

      list.appendChild(trashBin);
    }

    stations.forEach(s => {
      const el = document.createElement('div');
      el.className = 'station-card';
      el.dataset.id = s.id;
      if (isAdmin) {
        el.draggable = true;
        el.addEventListener('dragstart', e => {
          draggedStation = s.id;
          draggedStationCard = el;
          el.classList.add('dragging');
          e.dataTransfer.effectAllowed = 'move';
        });
        el.addEventListener('dragend', () => {
          el.classList.remove('dragging');
          draggedStation = null;
          draggedStationCard = null;
        });
      }

      el.innerHTML = `
        <div>
          <div style="font-weight:700">${s.name}</div>
          <div style="color:var(--muted);font-size:0.9rem">${s.availability?.slotsFree ?? '?'} slots libres</div>
        </div>
        <div style="text-align:right">
          <div style="width:36px;height:36px;border-radius:10px;background:${s.color};margin:0 auto 6px"></div>
          <button class="btn ghost small" data-id="${s.id}">Ver</button>
        </div>`;

      list.appendChild(el);
      el.querySelector('button')?.addEventListener('click', () => { panToStation(s); });
    });
  }

  // Panel control
  function openAddPanel(){ const panel = $('#addStationPanel'); if(!panel) return; panel.classList.remove('slide-hidden'); panel.classList.add('slide-visible'); panel.setAttribute('aria-hidden','false'); }
  function closeAddPanel(){ const panel = $('#addStationPanel'); if(!panel) return; panel.classList.remove('slide-visible'); panel.classList.add('slide-hidden'); panel.setAttribute('aria-hidden','true'); }

  // ---- Auth handlers (IMPORTANTE: evitar que el form recargue) ----
  function initAuth(){
    const loginForm = $('#loginForm');
    const registerForm = $('#registerForm');

    if (loginForm) {
      loginForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const uname = (loginForm.username.value || '').trim();
        if (!uname) { alert('Escribe un usuario'); return; }
        loginUser(uname);
        // para debug:
        console.log('Login OK, user:', uname);
        window.location.href = 'dashboard.html';
      });
    }

    if (registerForm) {
      registerForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const uname = (registerForm.username.value || '').trim();
        if (!uname) { alert('Escribe un usuario'); return; }
        loginUser(uname);
        console.log('Register + auto-login OK:', uname);
        window.location.href = 'dashboard.html';
      });
    }
  }

  // ---- resize handler ----
  function ensureResizeHandler(){
    if (window._fillzy_resize_installed) return;
    window._fillzy_resize_installed = true;
    window.addEventListener('resize', () => {
      const stations = loadStations();
      if (window._fillzy_resize_timeout) clearTimeout(window._fillzy_resize_timeout);
      window._fillzy_resize_timeout = setTimeout(()=> {
        if (mapInstance) mapInstance.resize();
        else renderMapFallback(stations);
      }, 150);
    });
  }

  // ---- init dashboard ----
  function initDashboard(){
    const user = getUser();
    if(!user) { location.href = 'login.html'; return; }

    renderHeaderForUser();

    const stations = loadStations();
    updateStats(stations);
    renderStationList(stations);

    // color grid
    const palette = ['#ff6b6b','#ff9f43','#ffd166','#6bffb0','#6b9bff','#c792ff','#ff6bb0','#6bffdf','#ffffff','#9aa4ad','#7b7f85','#ffb3b3'];
    const grid = $('#colorGrid'); 
    if (grid) { 
      grid.innerHTML = ''; 
      palette.forEach(c => { 
        const sw = document.createElement('div'); 
        sw.className = 'color-swatch'; 
        sw.style.background = c; 
        sw.dataset.color = c;
        sw.draggable = true; // Hacer arrastrable
        sw.addEventListener('dragstart', handleDragStart);
        sw.addEventListener('dragend', handleDragEnd);
        grid.appendChild(sw); 
      }); 
    }

    const closeBtn = $('#closePanel'); if (closeBtn) closeBtn.addEventListener('click', closeAddPanel);
    const addForm = $('#addStationForm');
    if (addForm) addForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.target;
      const name = form.name.value.trim();
      let lat = parseFloat(form.lat.value);
      let lng = parseFloat(form.lng.value);
      
      if ((!lat || !lng) && selectedLocation) {
        lat = selectedLocation.lat;
        lng = selectedLocation.lng;
      }

      if(!name || isNaN(lat) || isNaN(lng)){ 
        alert('Completa el nombre y asegúrate de arrastrar un color al mapa o ingresar coordenadas válidas'); 
        return; 
      }

      const capacity = parseInt(form.capacity.value || '4', 10);
      const tariff = parseFloat(form.tariff.value || '0');
      const selected = $$('.color-swatch', grid || document).find(n => n.classList.contains('selected'));
      const color = selected ? selected.dataset.color : draggedColor || '#6b9bff';

      try {
        const stations = loadStations();
        const id = 's' + Date.now();
        const newStation = { 
          id, name, lat, lng, color, capacity, 
          tariffs: [{type: 'Regular', price: tariff}], 
          availability: {slotsFree: Math.max(1, Math.floor(capacity/2))} 
        };
        
        stations.push(newStation);
        saveStations(stations);
        
        // Mantener el marcador temporal como si fuera el real
        if (tempMarker) {
          markersMap[id] = tempMarker;
          tempMarker = null;
        }

        updateStats(stations);
        renderStationList(stations);

        // Limpiar form y cerrar panel
        form.reset();
        closeAddPanel();
        
        // Hacer zoom suave a la nueva ubicación
        googleMapInstance.panTo({ lat, lng });
        if (googleMapInstance.getZoom() < 14) {
          googleMapInstance.setZoom(14);
        }
      } catch (error) {
        console.error('Error al guardar:', error);
        if (tempMarker) {
          tempMarker.setMap(null);
          tempMarker = null;
        }
        alert('Error al guardar la estación');
      }
    });

    ensureResizeHandler();
    initMapAndMarkers(stations);
    installPopupDelegation();
  }

  function handleDragStart(e) {
    draggedColor = e.target.dataset.color;
    e.target.classList.add('dragging');
    
    // Crear y configurar preview
    previewElement = document.createElement('div');
    previewElement.className = 'station-preview';
    previewElement.style.background = draggedColor;
    previewElement.style.opacity = '0.8';
    document.body.appendChild(previewElement);
    
    // Establecer datos para el drag
    e.dataTransfer.setData('text/plain', draggedColor);
    e.dataTransfer.effectAllowed = 'copy';
  }

  function handleDragEnd(e) {
    e.target.classList.remove('dragging');
    if (previewElement) {
      previewElement.remove();
      previewElement = null;
    }
  }

  function initDragAndDrop() {
    const mapElement = $('#map');
    if (!mapElement || !googleMapInstance) return;

    mapElement.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (previewElement) {
            previewElement.style.left = `${e.clientX}px`;
            previewElement.style.top = `${e.clientY}px`;
        }
    });

    mapElement.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!draggedColor || !googleMapInstance) return;

        // Limpiar marcador anterior
        if (tempMarker) {
            tempMarker.setMap(null);
        }

        const bounds = mapElement.getBoundingClientRect();
        const x = e.clientX - bounds.left;
        const y = e.clientY - bounds.top;

        try {
            const scale = Math.pow(2, googleMapInstance.getZoom());
            const worldPoint = new google.maps.Point(
                x / scale,
                y / scale
            );

            const ne = googleMapInstance.getBounds().getNorthEast();
            const sw = googleMapInstance.getBounds().getSouthWest();
            
            selectedLocation = {
                lat: ne.lat() - (y / mapElement.offsetHeight) * (ne.lat() - sw.lat()),
                lng: sw.lng() + (x / mapElement.offsetWidth) * (ne.lng() - sw.lng())
            };

            // Crear nuevo marcador temporal
            tempMarker = new google.maps.Marker({
                position: selectedLocation,
                map: googleMapInstance,
                icon: {
                    path: google.maps.SymbolPath.CIRCLE,
                    fillColor: draggedColor,
                    fillOpacity: 1,
                    strokeWeight: 2,
                    strokeColor: '#ffffff',
                    scale: 10
                },
                animation: google.maps.Animation.DROP
            });

            // Actualizar inputs
            const latInput = $('input[name="lat"]');
            const lngInput = $('input[name="lng"]');
            if (latInput) latInput.value = selectedLocation.lat.toFixed(6);
            if (lngInput) lngInput.value = selectedLocation.lng.toFixed(6);

            // Seleccionar el color en la grilla
            const colorSwatches = $$('.color-swatch');
            colorSwatches.forEach(swatch => {
                swatch.classList.remove('selected');
                if (swatch.dataset.color === draggedColor) {
                    swatch.classList.add('selected');
                }
            });

        } catch (error) {
            console.error('Error al colocar el marcador:', error);
        }

        draggedColor = null;
    });
  }

  // Actualizar el manejo del cierre del panel
  function closeAddPanel() {
    const panel = $('#addStationPanel');
    if (!panel) return;
    
    // Limpiar el marcador temporal
    if (tempMarker) {
        tempMarker.setMap(null);
        tempMarker = null;
    }
    
    panel.classList.remove('slide-visible');
    panel.classList.add('slide-hidden');
    panel.setAttribute('aria-hidden', 'true');
  }

  // ---- router init ----
  function init(){
    const page = document.body.id;
    console.log('Fillzy init, page id =', page);
    if(page === 'page-landing') {
      // si tienes una landing: initLanding() si la implementas
    }
    if(page === 'page-auth') initAuth();
    if(page === 'page-dashboard') initDashboard();
  }

  document.addEventListener('DOMContentLoaded', init);
})();