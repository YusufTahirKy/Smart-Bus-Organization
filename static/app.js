const API_BASE = 'http://localhost:8000/api';
let analysisChartInstance = null;

// --- Login ---
const VALID_USER = 'iett_admin';
const VALID_PASS = 'iett2024';
let isLoggedIn = false;

function attemptLogin() {
    const u = document.getElementById('adminUser')?.value.trim();
    const p = document.getElementById('adminPass')?.value.trim();
    if (u === VALID_USER && p === VALID_PASS) {
        isLoggedIn = true;
        document.getElementById('loginPanel')?.classList.add('hidden');
        document.getElementById('loginSuccess')?.classList.remove('hidden');
        showToast('Giriş başarılı! Hoş geldiniz.');
    } else {
        showToast('Hatalı kullanıcı adı veya şifre!', 'danger');
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    switchTab('dashboard');
    fetchState();         // ilk yükleme
    fetchLogs();
    fetchRoutesList();
    fetchFullNotifications();

    // Canlı güncelleme: her 10 saniyede bir
    setInterval(fetchState, 10000);
    setInterval(fetchLogs, 30000);
    setInterval(fetchFullNotifications, 30000);
});

// Format date
function updateTime() {
    const now = new Date();
    document.getElementById('lastUpdate').textContent = `Son Güncelleme: ${now.toLocaleTimeString()}`;
}

// Fetch and render state
async function fetchState() {
    try {
        const res = await fetch(`${API_BASE}/state`);
        const json = await res.json();

        if (json.status === 'success') {
            renderRoutes(json.data);
            updateTime();
        }
    } catch (e) {
        console.error("Error fetching state:", e);
    }
}

// Fetch and render reroute logs
async function fetchLogs() {
    try {
        const res = await fetch(`${API_BASE}/reroutes`);
        const json = await res.json();

        if (json.status === 'success') {
            renderLogs(json.data);
        }
    } catch (e) {
        console.error("Error fetching logs:", e);
    }
}

function renderRoutes(routes) {
    const container = document.getElementById('routesList');
    if (!routes || routes.length === 0) {
        container.innerHTML = '<div class="loading">Şu anki saat için veri bulunamadı.</div>';
        return;
    }

    container.innerHTML = routes.map(r => {
        // Scale: real score range is 0.06 – 1.49, cap at 1.5 for 100%
        const percent = Math.min(100, (r.effective_score / 1.5) * 100);

        // Use total_passengers if backend provides it; fallback calculation
        const totalPassengers = Math.round(r.total_passengers ?? (r.base_avg_passengers * r.buses_on_route));
        const buses = Math.round(r.buses_on_route);

        // Human-readable status labels
        const statusLabel = {
            'overcrowded': 'Aşırı Yoğun',
            'normal': 'Normal',
            'undercrowded': 'Seyrek'
        }[r.status] || r.status;

        return `
        <div class="route-card status-${r.status}">
            <div class="route-badge">${r.route}</div>
            <div class="route-stats">
                <div class="route-title">${r.route_desc || 'Bilinmeyen Hat'}</div>
                <div class="route-subtitle"><i class="fa-solid fa-location-dot"></i> Yoğun Durak: ${r.busiest_station || 'Bilinmiyor'}</div>
                <div class="stat-labels">
                    <span><i class="fa-solid fa-bus"></i> ${buses} Otobüs</span>
                    <span><i class="fa-solid fa-users"></i> ~${totalPassengers} Yolcu</span>
                    <span class="status-label-${r.status}">${statusLabel}</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-fill" style="width: ${percent}%"></div>
                </div>
            </div>
            <div class="route-score">${r.effective_score.toFixed(2)}</div>
        </div>
        `;
    }).join('');
}

function renderLogs(logs) {
    const container = document.getElementById('reroutesList');
    if (!container) return; 

    // Proximity Filtering
    let filteredLogs = logs;
    const currentRouteCode = document.getElementById('routeCurrentLine')?.value.toUpperCase().trim();
    
    if (currentRouteCode && mapDataCache) {
        const currentRouteData = mapDataCache.find(r => r.route === currentRouteCode);
        if (currentRouteData) {
            filteredLogs = logs.filter(log => {
                const targetData = mapDataCache.find(r => r.route === log.original_route || r.route === log.helping_route);
                if (!targetData) return true;
                const dist = calculateDistance(currentRouteData.lat, currentRouteData.lng, targetData.lat, targetData.lng);
                return dist <= 5; // Sadece 5 km çapındaki olayları göster
            });
        }
    }

    if (!filteredLogs || filteredLogs.length === 0) {
        container.innerHTML = '<div class="loading">Yakınınızda son yönlendirme bulunamadı.</div>';
        return;
    }

    container.innerHTML = filteredLogs.map(log => {
        const safeIso = log.timestamp.includes('T') ? log.timestamp : log.timestamp.replace(' ', 'T');
        const d = new Date(safeIso + (safeIso.endsWith('Z') ? '' : 'Z')); 
        return `
        <div class="log-item">
            <div class="log-time">${d.toLocaleTimeString()}</div>
            <div class="log-route">${log.original_route} <i class="fa-solid fa-arrow-right"></i> ${log.helping_route}</div>
            <div class="log-detail">Sürücü: ${log.driver_id}</div>
        </div>
        `;
    }).join('');
}

// Actions
async function sendDriverSignal(type) {
    const driverId = document.getElementById('routeDriverId').value.trim();
    const route = document.getElementById('routeCurrentLine').value.toUpperCase().trim();

    if (!driverId || !route) {
        showToast('Lütfen Sürücü ID ve Mevcut Hattınızı girin.', 'danger');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/signal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ driver_id: driverId, route: route, signal: type })
        });
        const json = await res.json();
        if (json.status === 'success') {
            showToast(`Durumunuz (${type}) merkeze iletildi!`, 'success');
            fetchRecommendedRoutes(); // Refresh recommendations just in case
            fetchState(); // refresh
        }
    } catch (e) {
        showToast('Bağlantı hatası!', 'danger');
    }
}

async function acceptReroute(toRoute) {
    const driverId = document.getElementById('routeDriverId').value.trim();
    const fromRoute = document.getElementById('routeCurrentLine').value.toUpperCase().trim();

    if (!driverId || !fromRoute) {
        showToast('Devam etmeden önce Şoför ID ve Mevcut Hattınızı girmelisiniz.', 'warning');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/driver_reroute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ driver_id: driverId, original_route: fromRoute, helping_route: toRoute })
        });
        const json = await res.json();
        if (json.status === 'success') {
            showToast(json.message, 'success');
            document.getElementById('routeCurrentLine').value = toRoute; // Sürücünün hattı güncellendi
            fetchRecommendedRoutes(); // Listeyi yenile
            fetchState(); // Göstergeleri yenile
            fetchLogs(); // Yönlendirme loglarını yenile
        } else {
            showToast(json.message || 'Yönlendirme başarısız.', 'danger');
        }
    } catch (e) {
        showToast('Bağlantı hatası!', 'danger');
    }
}

function calculateDistance(lat1, lon1, lat2, lon2) {
    if (!lat1 || !lon1 || !lat2 || !lon2) return Infinity;
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c; 
}

// Otomatik senkronizasyon (Şoför id/hat girdiğinde veya değiştirdiğinde)
let syncTimeout = null;
function syncDriverContext() {
    clearTimeout(syncTimeout);
    syncTimeout = setTimeout(() => {
        const route = document.getElementById('routeCurrentLine').value.trim();
        if (route.length > 2) {
            fetchRecommendedRoutes();
        } else if (route.length === 0) {
            // Temizlenirse global haline geri dönsün
            fetchRecommendedRoutes();
        }
    }, 500); // 500ms debounce
}

async function fetchRecommendedRoutes() {
    const container = document.getElementById('recommendedRoutesList');
    const currentRouteCode = document.getElementById('routeCurrentLine')?.value.toUpperCase().trim();
    
    // UI'daki diğer panelleri de anında yeni hatta göre filtrele/güncelle
    fetchFullNotifications();
    fetchLogs();

    if (!container) return;
    container.innerHTML = '<div class="loading"><i class="fa-solid fa-robot fa-spin"></i> Yapay Zeka en yakın rotaları analiz ediyor...</div>';

    if (!mapDataCache) {
        // Harita verisi yoksa çekmeye çalış
        await fetchMapRoutes();
    }

    try {
        const res = await fetch(`${API_BASE}/state`);
        const json = await res.json();
        
        if (json.status === 'success' && json.data.length > 0) {
            // Sadece overcrowded olanları filtrele
            let overcrowded = json.data.filter(r => r.status === 'overcrowded');
            
            if (overcrowded.length === 0) {
                container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--success);"><i class="fa-solid fa-check-circle" style="font-size: 2rem; margin-bottom: 10px;"></i><br>Şu an sistemde acil destek gerektiren kırmızı bir hat bulunmuyor. Mevcut hattınızda devam edebilirsiniz.</div>';
                return;
            }

            // Eğer sürücü kendi hattını girdiyse mesafe bazlı sıralama (AI implementasyonu)
            let currentRouteData = null;
            if (currentRouteCode && mapDataCache) {
                currentRouteData = mapDataCache.find(r => r.route === currentRouteCode);
            }

            if (currentRouteData) {
                // Şoförün kendi hattını listeden çıkar
                overcrowded = overcrowded.filter(r => r.route !== currentRouteCode);

                // Mesafe hesapla
                overcrowded = overcrowded.map(route => {
                    const mapMatch = mapDataCache.find(m => m.route === route.route);
                    const distance = mapMatch ? calculateDistance(currentRouteData.lat, currentRouteData.lng, mapMatch.lat, mapMatch.lng) : Infinity;
                    return { ...route, distance: distance };
                });
                
                // Mesafeye göre sırala (yakın olan en üstte)
                overcrowded.sort((a, b) => a.distance - b.distance);
                // Sadece çok yakın (örneğin 5 km içindeki) 5 tanesini göster
                overcrowded = overcrowded.filter(r => r.distance <= 5).slice(0, 5);
                
                if (overcrowded.length === 0) {
                    container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--success);"><i class="fa-solid fa-check-circle" style="font-size: 2rem; margin-bottom: 10px;"></i><br>Yakınınızda acil destek gerektiren kırmızı bir hat bulunmuyor.</div>';
                    return;
                }
            } else {
                // Konum bilinmiyorsa yoğunluğa göre sırala
                overcrowded.sort((a,b) => b.effective_score - a.effective_score);
            }

            container.innerHTML = overcrowded.map(r => {
                const distanceText = r.distance !== undefined && r.distance !== Infinity 
                    ? `<span style="background: var(--bg-secondary); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;"><i class="fa-solid fa-location-arrow"></i> ~${r.distance.toFixed(1)} km uzakta</span>` 
                    : '';

                return `
                <div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid var(--danger); padding: 16px; border-radius: 4px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <div>
                            <div style="font-weight: 700; font-size: 1.1rem; color: var(--text-main); margin-bottom: 4px;">Hat: ${r.route}</div>
                            <div style="font-size: 0.85rem; color: var(--text-muted);">${r.route_desc || 'Bilinmeyen Güzergah'}</div>
                        </div>
                        <span style="background: var(--danger); color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">Acil Destek</span>
                    </div>
                    <div style="display: flex; gap: 16px; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 16px; align-items: center; flex-wrap: wrap;">
                        <span><i class="fa-solid fa-users"></i> Bekleyen: ~${Math.round(r.total_passengers ?? (r.base_avg_passengers * r.buses_on_route))}</span>
                        <span><i class="fa-solid fa-bus"></i> Aktif: ${Math.round(r.buses_on_route)}</span>
                        ${distanceText}
                    </div>
                    <button class="btn btn-primary" onclick="acceptReroute('${r.route}')" style="width: 100%; display: flex; justify-content: center; gap: 8px;">
                        <i class="fa-solid fa-code-merge"></i> AI Önerisini Seç & Geçiş Yap
                    </button>
                </div>
            `}).join('');
        }
    } catch (e) {
        container.innerHTML = '<div class="loading" style="color: var(--danger);">Veri çekilemedi. Bağlantınızı kontrol edin.</div>';
    }
}


async function triggerCycle() {
    showToast('Manuel rotalama tetiklendi. Hesaplanıyor...');
    try {
        const res = await fetch(`${API_BASE}/trigger_cycle`, { method: 'POST' });
        const json = await res.json();
        if (json.status === 'success') {
            setTimeout(() => {
                fetchState();
                fetchLogs();
            }, 2000); // Wait for background task to complete roughly
        }
    } catch (e) {
        showToast('Bağlantı hatası!');
    }
}

function showToast(msg, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.style.background = type === 'danger' ? 'var(--danger)' : 'var(--success)';
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}


// --- Theme & Mobile ---
function initTheme() {
    const isLight = localStorage.getItem('theme') === 'light';
    if (isLight) {
        document.documentElement.classList.add('light-mode');
        document.getElementById('themeToggleBtn').innerHTML = '<i class="fa-solid fa-moon"></i>';
    }
}

function toggleTheme() {
    const html = document.documentElement;
    html.classList.toggle('light-mode');
    const isLight = html.classList.contains('light-mode');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');

    const btn = document.getElementById('themeToggleBtn');
    btn.innerHTML = isLight ? '<i class="fa-solid fa-moon"></i>' : '<i class="fa-solid fa-sun"></i>';

    // If analysis tab is active, redraw the chart to update colors
    if (document.getElementById('tab-density-analysis').classList.contains('active')) {
        loadRouteAnalysis();
    }
}

function toggleMobileMenu() {
    document.querySelector('.sidebar').classList.toggle('open');
}

// --- Tabs ---
function switchTab(tabId) {
    document.querySelector('.sidebar').classList.remove('open');

    // Nav aktif güncelle
    document.querySelectorAll('.nav-menu a, .mobile-bottom-nav a').forEach(a => {
        a.classList.remove('active');
        if (a.getAttribute('onclick') && a.getAttribute('onclick').includes(tabId)) {
            a.classList.add('active');
        }
    });

    // Tüm sekmeleri gizle (display:none ile — class'a bağımlı değil)
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });

    // Seçili sekmeyi göster
    const selected = document.getElementById(`tab-${tabId}`);
    if (selected) selected.style.display = 'flex';

    // Sekmeye özel işlemler
    const title = document.getElementById('pageTitle');
    const manualBtn = document.getElementById('manualRouteBtn');

    if (tabId === 'dashboard') {
        title.textContent = 'Sistem Kontrol Paneli';
        manualBtn.style.display = 'inline-block';
        fetchState();
    } else if (tabId === 'route-analysis') {
        title.textContent = 'Şoför Rota Seçimi';
        manualBtn.style.display = 'none';
        fetchRecommendedRoutes();
    } else if (tabId === 'density-analysis') {
        title.textContent = 'Rota Yoğunluk Analizi';
        manualBtn.style.display = 'none';
        setTimeout(() => {
            initMap();
            loadAllRoutesOnMap();
        }, 100);
        if (!document.getElementById('routeSelect').value) {
            const select = document.getElementById('routeSelect');
            if (select && select.options && select.options.length > 1) {
                select.selectedIndex = 1;
                loadRouteAnalysis();
            }
        }
    } else if (tabId === 'notifications') {
        title.textContent = 'Sistem Bildirimleri';
        manualBtn.style.display = 'none';
        fetchFullNotifications();
    }
}

// --- Analysis Tab ---
let mapDataCache = null;
async function fetchRoutesList() {
    try {
        const res = await fetch(`${API_BASE}/map_routes`);
        const json = await res.json();
        if (json.status === 'success') {
            mapDataCache = json.data.routes;
            const select = document.getElementById('routeSelect');
            select.innerHTML = '';
            mapDataCache.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.route;
                opt.textContent = `${r.route} (${r.town})`;
                select.appendChild(opt);
            });
            console.log("Successfully loaded route map data.");
        }
    } catch (e) { console.error("Error fetching routes:", e); }
}

async function loadRouteAnalysis() {
    const route = document.getElementById('routeInput').value.toUpperCase().trim();
    if (!route || !mapDataCache) return;

    initMap();
    clearMapMarkers();

    const routeData = mapDataCache.find(r => r.route === route);

    // Place all routes as small background markers
    mapDataCache.forEach(r => {
        const isSelected = r.route === route;
        placeRouteMarker(r.route, r.demand_score, r.town, r.line, isSelected);
    });

    if (routeData) {
        // Update Info Card
        const card = document.getElementById('routeInfoCard');
        document.getElementById('infoRouteName').textContent = routeData.route;
        document.getElementById('infoRouteDesc').textContent = routeData.line || '';
        const statusEl = document.getElementById('infoStatus');
        
        statusEl.textContent = getStatusText(routeData.demand_score);
        if (routeData.demand_score > 1.0) {
            statusEl.style.background = 'rgba(239,68,68,0.2)';
            statusEl.style.color = '#ef4444';
        } else if (routeData.demand_score < 0.80) {
            statusEl.style.background = 'rgba(16,185,129,0.2)';
            statusEl.style.color = '#10b981';
        } else {
            statusEl.style.background = 'rgba(245,158,11,0.2)';
            statusEl.style.color = '#f59e0b';
        }
        card.style.display = 'flex';

        // Center map
        busMap.setView([routeData.lat, routeData.lng], 13);

        // Draw Chart
        const hourlyData = routeData.hourly || [];
        hourlyData.sort((a,b) => a.hour - b.hour);
        const chartData = hourlyData.map(d => ({
            hour: d.hour,
            base_avg_passengers: d.avg_passengers,
            buses_on_route: Math.max(1, Math.round(d.avg_passengers / 50)) // Estimate buses needed
        }));
        drawChart(chartData, route);
    }
}

function drawChart(data, route) {
    const ctx = document.getElementById('analysisChart').getContext('2d');

    const labels = data.map(d => `${String(d.hour).padStart(2, '0')}:00`);
    const passengers = data.map(d => d.base_avg_passengers);
    const buses = data.map(d => d.buses_on_route);

    if (analysisChartInstance) {
        analysisChartInstance.destroy();
    }

    const isLight = document.documentElement.classList.contains('light-mode');
    const textColor = isLight ? '#475569' : '#94a3b8';
    const gridColor = isLight ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.1)';

    analysisChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Ortalama Yolcu',
                    data: passengers,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.2)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    yAxisID: 'y'
                },
                {
                    label: 'Aktif Otobüs',
                    data: buses,
                    borderColor: '#10b981',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0.1,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: textColor } },
                title: { display: true, text: `${route} Günlük Gidişat`, color: textColor }
            },
            scales: {
                x: { ticks: { color: textColor }, grid: { color: gridColor } },
                y: {
                    type: 'linear', display: true, position: 'left',
                    ticks: { color: textColor }, grid: { color: gridColor },
                    title: { display: window.innerWidth > 768, text: 'Yolcu Sayısı', color: textColor }
                },
                y1: {
                    type: 'linear', display: true, position: 'right',
                    ticks: { color: textColor }, grid: { drawOnChartArea: false },
                    title: { display: window.innerWidth > 768, text: 'Otobüs Sayısı', color: textColor }
                }
            }
        }
    });
}

// --- Notifications Tab ---
let allNotifications = [];

// Alias for the new index.html buttons
const reportEvent = sendDriverSignal;

async function fetchFullNotifications() {
    const listEl = document.getElementById('notificationsList');
    if (!listEl) return;

    try {
        const [notifRes, stateRes] = await Promise.all([
            fetch(`${API_BASE}/notifications`),
            fetch(`${API_BASE}/state`)
        ]);
        const notifJson = await notifRes.json();
        const stateJson = await stateRes.json();

        const notifications = [];

        // Build notifications from DB events
        if (notifJson.status === 'success' && notifJson.data) {
            notifJson.data.forEach((log, i) => {
                const safeIso = log.timestamp.includes('T') ? log.timestamp : log.timestamp.replace(' ', 'T');
                const d = new Date(safeIso + (safeIso.endsWith('Z') ? '' : 'Z'));
                let type, icon, title, detail;

                if (log.type === 'reroute') {
                    type = 'warning';
                    icon = 'fa-shuffle';
                    title = `Yönlendirme: ${log.action}`;
                    detail = `Hat: ${log.route}`;
                } else if (log.type === 'signal') {
                    if (log.action === 'kaza') {
                        type = 'danger';
                        icon = 'fa-car-burst';
                        title = `Kritik Bildirim: Kaza Var`;
                        detail = `Hat: ${log.route} | Sürücü: ${log.driver_id}`;
                    } else if (log.action === 'yol_calismasi') {
                        type = 'success'; // User requested "normale de yaz bişiler normalde yol çalışması var yazsın"
                        icon = 'fa-person-digging';
                        title = `Normal: Yol Çalışması Var`;
                        detail = `Hat: ${log.route} | Sürücü: ${log.driver_id}`;
                    } else if (log.action === 'yogun_trafik') {
                        type = 'warning';
                        icon = 'fa-traffic-light';
                        title = `Uyarı: Yoğun Trafik`;
                        detail = `Hat: ${log.route} | Sürücü: ${log.driver_id}`;
                    } else if (log.action === 'full') {
                        type = 'danger';
                        icon = 'fa-users';
                        title = `Kritik Uyarı: Aşırı Dolu`;
                        detail = `Hat: ${log.route} | Sürücü: ${log.driver_id}`;
                    } else {
                        type = 'success';
                        icon = 'fa-check-circle';
                        title = `Durum Bildirimi: ${log.action}`;
                        detail = `Hat: ${log.route} | Sürücü: ${log.driver_id}`;
                    }
                }

                notifications.push({
                    id: `notif-${i}`,
                    type: type,
                    routeCode: log.route, // Eksik olan routeCode eklendi!
                    icon: icon,
                    title: title,
                    detail: detail,
                    time: d,
                    timeStr: d.toLocaleString('tr-TR')
                });
            });
        }

        // Build notifications from route state (overcrowded ones)
        if (stateJson.status === 'success' && stateJson.data) {
            stateJson.data.forEach((r, i) => {
                if (r.status === 'overcrowded') {
                    notifications.push({
                        id: `danger-${i}`,
                        type: 'danger',
                        routeCode: r.route, // added for filtering
                        icon: 'fa-triangle-exclamation',
                        title: `Sistem Uyarısı: Aşırı Yoğun Hat ${r.route}`,
                        detail: `${r.route_desc || ''} — Yoğun Durak: ${r.busiest_station || 'Bilinmiyor'} | Skor: ${r.effective_score.toFixed(2)}`,
                        time: new Date(),
                        timeStr: 'Şu an'
                    });
                }
            });
        }

        // Proximity Filtering
        let filteredNotifications = notifications;
        const currentRouteCode = document.getElementById('routeCurrentLine')?.value.toUpperCase().trim();
        
        if (currentRouteCode && mapDataCache) {
            const currentRouteData = mapDataCache.find(r => r.route === currentRouteCode);
            if (currentRouteData) {
                filteredNotifications = notifications.filter(n => {
                    let routeCode = n.routeCode; 
                    if (!routeCode && n.detail && n.detail.includes('Hat:')) {
                        // Extract route from "Hat: 500T | Sürücü: DRV-101"
                        const match = n.detail.match(/Hat:\s*([A-Z0-9]+)/);
                        if (match) routeCode = match[1];
                    }
                    if (!routeCode) return true; // keep if we can't determine route

                    const targetData = mapDataCache.find(r => r.route === routeCode);
                    if (!targetData) return true;
                    
                    const dist = calculateDistance(currentRouteData.lat, currentRouteData.lng, targetData.lat, targetData.lng);
                    return dist <= 5; // Only within 5 km
                });
            }
        }

        // Sort newest first
        filteredNotifications.sort((a, b) => b.time - a.time);
        allNotifications = filteredNotifications;

        // Update badge count
        const badgeEl = document.getElementById('notifCount');
        if (badgeEl) badgeEl.textContent = filteredNotifications.length;

        // Özet stat kartlarını güncelle
        const s = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        s('statCritical', filteredNotifications.filter(n => n.type === 'danger').length);
        s('statWarning', filteredNotifications.filter(n => n.type === 'warning').length);
        s('statNormal', filteredNotifications.filter(n => n.type === 'success').length);
        s('statTotal', filteredNotifications.length);

        renderNotifications(filteredNotifications);

    } catch (e) {
        console.error("Error fetching notifications:", e);
        if (listEl) listEl.innerHTML = `
            <div class="notif-empty">
                <i class="fa-solid fa-wifi" style="color: var(--danger)"></i>
                <p>Sunucuya bağlanılamadı</p>
                <span>Lütfen backend'in çalıştığını kontrol edin</span>
            </div>`;
    }
}

function renderNotifications(list) {
    const listEl = document.getElementById('notificationsList');
    if (!listEl) return;

    if (!list || list.length === 0) {
        listEl.innerHTML = `
            <div class="notif-empty">
                <i class="fa-solid fa-bell-slash"></i>
                <p>Bildirim bulunamadı</p>
                <span>Bu kategoride gösterilecek olay yok</span>
            </div>`;
        return;
    }

    listEl.innerHTML = list.map(n => `
        <div class="notif-item notif-${n.type}" data-type="${n.type}">
            <div class="notif-item-icon">
                <i class="fa-solid ${n.icon}"></i>
            </div>
            <div class="notif-item-body">
                <div class="notif-item-title">${n.title}</div>
                <div class="notif-item-detail">${n.detail}</div>
            </div>
            <div class="notif-item-time">${n.timeStr}</div>
        </div>
    `).join('');
}

function filterNotifications(type, btn) {
    // Update active chip
    document.querySelectorAll('.notif-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');

    if (type === 'all') {
        renderNotifications(allNotifications);
    } else {
        renderNotifications(allNotifications.filter(n => n.type === type));
    }
}

function clearAllNotifications() {
    allNotifications = [];
    const badgeEl = document.getElementById('notifCount');
    if (badgeEl) badgeEl.textContent = '0';
    renderNotifications([]);
}

// --- Chat Box ---
function toggleChat() {
    const chatWidget = document.getElementById('chatWidget');
    chatWidget.classList.toggle('open');
}

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;

    // Add user message to UI
    const chatBody = document.getElementById('chatBody');
    chatBody.innerHTML += `<div class="chat-message user">${msg}</div>`;
    input.value = '';
    chatBody.scrollTop = chatBody.scrollHeight;

    // Send to API
    try {
        const res = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        const json = await res.json();

        // Add bot message
        chatBody.innerHTML += `<div class="chat-message assistant">${json.response || "Bağlantı hatası."}</div>`;
        chatBody.scrollTop = chatBody.scrollHeight;
    } catch (e) {
        chatBody.innerHTML += `<div class="chat-message assistant" style="color: var(--danger)">Hata: Sunucuya bağlanılamadı.</div>`;
        chatBody.scrollTop = chatBody.scrollHeight;
    }
}

// --- Leaflet Map ---
let busMap = null;
let mapMarkers = [];

const ISTANBUL_CENTER = [41.0082, 28.9784];

function initMap() {
    if (busMap) return;
    const isDark = !document.documentElement.classList.contains('light-mode');
    busMap = L.map('routeMap', { center: ISTANBUL_CENTER, zoom: 11, zoomControl: true });
    const tileUrl = isDark
        ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
        : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
    L.tileLayer(tileUrl, { attribution: '© OpenStreetMap contributors © CARTO', maxZoom: 19 }).addTo(busMap);
}

function clearMapMarkers() {
    mapMarkers.forEach(m => busMap.removeLayer(m));
    mapMarkers = [];
}

function getMarkerColor(score) {
    if (score > 1.0) return "#ef4444";
    if (score < 0.80) return "#10b981";
    return "#f59e0b";
}

function getStatusText(score) {
    if (score > 1.0) return "🔴 Yoğun";
    if (score < 0.80) return "🟢 Sakin";
    return "🟡 Normal";
}

function placeRouteMarker(route, score, town, lineDesc, isHighlighted = false) {
    const routeData = mapDataCache.find(r => r.route === route);
    if (!routeData) return;
    
    // Add random jitter to coords so markers don't perfectly overlap
    const lat = routeData.lat + (Math.random() - 0.5) * 0.02;
    const lng = routeData.lng + (Math.random() - 0.5) * 0.02;
    
    const color = getMarkerColor(score);
    const radius = isHighlighted ? 18 : 10;

    const circle = L.circleMarker([lat, lng], {
        radius,
        fillColor: color,
        color: isHighlighted ? '#ffffff' : color,
        weight: isHighlighted ? 3 : 1,
        fillOpacity: isHighlighted ? 1.0 : 0.82,
    });

    const popupHtml = `
        <div style="font-family:Inter,sans-serif; min-width:170px; padding:4px;">
            <div style="font-weight:700; font-size:1rem; margin-bottom:4px;">🚌 Hat ${route}</div>
            <div style="color:#555; font-size:0.82rem; margin-bottom:6px;">${lineDesc || ''}</div>
            <div style="font-size:0.82rem;">📍 ${town || 'Bilinmiyor'}</div>
            <div style="font-size:0.82rem; margin-top:4px; font-weight:600;">${getStatusText(score)}</div>
        </div>`;

    circle.bindPopup(popupHtml);

    circle.bindTooltip(route, {
        permanent: isHighlighted,
        direction: 'top',
        className: 'leaflet-route-label'
    });

    circle.addTo(busMap);
    mapMarkers.push(circle);
    return circle;
}

async function loadAllRoutesOnMap() {
    initMap();
    clearMapMarkers();

    if (!mapDataCache) return;

    mapDataCache.forEach(r => {
        placeRouteMarker(r.route, r.demand_score, r.town, r.line);
    });

    busMap.setView(ISTANBUL_CENTER, 10);
}
