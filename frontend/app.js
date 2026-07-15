const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
    ? 'http://localhost:80/api' 
    : '/api';

function initApp() {
    // Tab Switching Logic
    const navLinks = document.querySelectorAll('.nav-links li');
    const tabContents = document.querySelectorAll('.tab-content');

    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            navLinks.forEach(l => l.classList.remove('active'));
            tabContents.forEach(t => t.classList.remove('active'));

            link.classList.add('active');
            const tabId = link.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');

            if (tabId === 'stocks') loadHoldings('Single', 'persona-stocks', 'stocks');
            if (tabId === 'etfs') loadHoldings('ETF', 'persona-etfs', 'etfs');
            if (tabId === 'olympic') loadOlympic();
            if (tabId === 'prodshadow') loadProdShadow();
            if (tabId === 'autopsy') loadAutopsy();
        });
    });

    // Persona Change Listeners
    document.getElementById('persona-stocks').addEventListener('change', () => {
        const select = document.getElementById('persona-stocks');
        const text = select.options[select.selectedIndex].text;
        const persona = select.value;
        document.getElementById('persona-stocks-label').innerText = text;
        document.getElementById('tab-broker-stocks').innerText = `💼 ${persona} Trade Ledger`;
        loadHoldings('Single', 'persona-stocks', 'stocks');
    });
    
    document.getElementById('persona-etfs').addEventListener('change', () => {
        const select = document.getElementById('persona-etfs');
        const text = select.options[select.selectedIndex].text;
        const persona = select.value;
        document.getElementById('persona-etfs-label').innerText = text;
        document.getElementById('tab-broker-etfs').innerText = `💼 ${persona} Trade Ledger`;
        loadHoldings('ETF', 'persona-etfs', 'etfs');
    });

    // Initial Load
    loadHoldings('Single', 'persona-stocks', 'stocks');

    // Live Auto-Polling Loop (Every 60,000ms = 1 minute)
    setInterval(() => {
        const activeTab = document.querySelector('.tab-link.active');
        if (!activeTab) return;
        const tabId = activeTab.getAttribute('data-tab');
        if (tabId === 'stocks') loadHoldings('Single', 'persona-stocks', 'stocks');
        else if (tabId === 'etfs') loadHoldings('ETF', 'persona-etfs', 'etfs');
        else if (tabId === 'olympic') loadOlympic();
        else if (tabId === 'prodshadow') loadProdShadow();
        else if (tabId === 'autopsy') loadAutopsy();
    }, 60000);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}

// --- AUTO Y-AXIS RECALIBRATION ---
function enableAutoYScale(divId) {
    const gd = document.getElementById(divId);
    if (!gd) return;
    gd.on('plotly_relayout', function(eventdata) {
        if (eventdata['xaxis.range[0]'] || eventdata['xaxis.range']) {
            let x0, x1;
            if (eventdata['xaxis.range']) {
                x0 = eventdata['xaxis.range'][0];
                x1 = eventdata['xaxis.range'][1];
            } else {
                x0 = eventdata['xaxis.range[0]'];
                x1 = eventdata['xaxis.range[1]'];
            }
            if (typeof x0 === 'string') x0 = new Date(x0).getTime();
            if (typeof x1 === 'string') x1 = new Date(x1).getTime();

            let yMin = Infinity;
            let yMax = -Infinity;

            gd.data.forEach(trace => {
                if (trace.hoverinfo === 'skip') return; // Ignore invisible anchor traces
                
                if (trace.x && trace.y) {
                    for (let i = 0; i < trace.x.length; i++) {
                        let tx = trace.x[i];
                        if (typeof tx === 'string') tx = new Date(tx).getTime();
                        if (tx >= x0 && tx <= x1) {
                            if (trace.y[i] < yMin) yMin = trace.y[i];
                            if (trace.y[i] > yMax) yMax = trace.y[i];
                        }
                    }
                }
            });

            if (yMin !== Infinity && yMax !== -Infinity) {
                // Prevent infinite loop: check if the event that triggered this was our own Y-axis zoom
                if (eventdata['yaxis.range[0]'] || eventdata['yaxis.range']) return;
                
                let pad = (yMax - yMin) * 0.1;
                // Add a minimum absolute padding so the Y-axis doesn't collapse when the line is flat
                const minPad = Math.abs(yMax) * 0.0025; // 0.25% minimum vertical margin
                if (pad < minPad) pad = minPad;
                
                Plotly.relayout(gd, { 'yaxis.range': [yMin - pad, yMax + pad] });
            }
        }
    });
}

const STD_LAYOUT = {
    plot_bgcolor: 'rgba(0,0,0,0)', 
    paper_bgcolor: 'rgba(0,0,0,0)',
    font: { color: 'white', size: 14 },
    margin: { t: 50, b: 120, l: 80, r: 20 },
    showlegend: true,
    legend: { orientation: "h", yanchor: "top", y: -0.5, xanchor: "center", x: 0.5, font: { size: 14 } }
};

async function loadHoldings(mode, selectId, prefix) {
    const persona = document.getElementById(selectId).value;
    
    // Fetch and populate Select View Dropdown Options
    try {
        const ddRes = await fetch(`${API_BASE}/dropdown?persona=${persona}&mode=${mode}`, { cache: 'no-store' });
        if (ddRes.ok) {
            const options = await ddRes.json();
            const sel = document.getElementById(`view-${prefix}`);
            const currentVal = sel.value;
            sel.innerHTML = '';
            options.forEach(opt => {
                const optionEl = document.createElement('option');
                optionEl.value = opt;
                optionEl.innerText = opt;
                sel.appendChild(optionEl);
            });
            if (options.includes(currentVal)) {
                sel.value = currentVal;
            }
        }
    } catch (e) {
        console.error("Failed to load dropdown options", e);
    }
    
    try {
        const response = await fetch(`${API_BASE}/holdings?persona=${persona}&mode=${mode}`, { cache: 'no-store' });
        if (!response.ok) throw new Error('Data not found');
        
        const data = await response.json();
        
        const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
        
        let eqText = formatter.format(data.total_equity);
        if (data.is_pending) {
            eqText += ' <span style="font-size: 0.5em; background: #FF851B; color: #111; padding: 2px 6px; border-radius: 4px; vertical-align: middle; margin-left: 8px; font-weight: bold; text-transform: uppercase;">PRE-MARKET (PENDING)</span>';
        }
        document.getElementById(`eq-${prefix}`).innerHTML = eqText;
        document.getElementById(`ret-${prefix}`).innerText = `${data.total_return > 0 ? '+' : ''}${data.total_return.toFixed(2)}%`;
        document.getElementById(`dd-${prefix}`).innerText = `${data.max_dd.toFixed(2)}%`;
        document.getElementById(`sharpe-${prefix}`).innerText = data.sharpe.toFixed(2);
        document.getElementById(`win-${prefix}`).innerText = `${data.win_rate.toFixed(1)}%`;

        const c_pal = ['#00E5FF', '#FF851B', '#B10DC9', '#FFDC00', '#FF4136', '#39CCCC'];
        const colors = data.chart_data.labels.map((l, i) => l === 'Cash' ? '#4CAF50' : c_pal[i % c_pal.length]);

        const trace = {
            labels: data.chart_data.labels,
            values: data.chart_data.values,
            type: 'pie',
            hole: 0.5,
            textinfo: 'label+percent',
            hoverinfo: 'label+value',
            textposition: 'outside',
            automargin: true,
            marker: { colors: colors }
        };

        Plotly.newPlot(`chart-${prefix}`, [trace], Object.assign({}, STD_LAYOUT, {
            margin: { t: 60, b: 60, l: 60, r: 60 },
            legend: { orientation: "v", x: 0.85, y: 0.5, font: { size: 14 } }
        }));

        // Line Chart
        const traceLine = {
            x: data.equity_curve.dates,
            y: data.equity_curve.equity,
            type: 'scatter',
            mode: 'lines',
            line: { color: '#00E5FF', width: 2 },
            name: 'Total Equity'
        };
        
        // Y-Axis Padding for Zoom (Invisible Anchors)
        if (data.equity_curve.equity && data.equity_curve.equity.length > 0) {
            let yMin = Math.min(...data.equity_curve.equity);
            let yMax = Math.max(...data.equity_curve.equity);
            let yPad = Math.max((yMax - yMin) * 0.20, Math.abs(yMax) * 0.02);
            
            const anchorTrace = {
                x: [data.equity_curve.dates[0], data.equity_curve.dates[0]],
                y: [yMin - yPad, yMax + yPad],
                mode: 'markers',
                marker: { color: 'rgba(0,0,0,0)' },
                showlegend: false,
                hoverinfo: 'skip'
            };
            
            const layoutLine = Object.assign({}, STD_LAYOUT, {
                title: { text: 'Historical Total Equity', font: { color: 'white' } },
                xaxis: { 
                    color: 'white', 
                    gridcolor: 'rgba(255,255,255,0.1)', 
                    dtick: 86400000, 
                    tickformat: '%b %d',
                    rangeslider: { visible: true, thickness: 0.08, bgcolor: '#383838', bordercolor: '#1E90FF', borderwidth: 1 } 
                },
                yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' }
            });
            const lineElement = document.getElementById(`line-${prefix}`);
            if (lineElement) {
                Plotly.newPlot(`line-${prefix}`, [traceLine, anchorTrace], layoutLine);
                enableAutoYScale(`line-${prefix}`);
            }
        }

        // Sort table: Currently Holding 'Yes' first, then sort by PnL descending. Lock TOTAL PnL to bottom.
        data.breakdown.sort((a, b) => {
            if (a.Asset === 'TOTAL PnL') return 1;
            if (b.Asset === 'TOTAL PnL') return -1;
            const holdingA = a['Currently Holding'] === 'Yes' ? 1 : 0;
            const holdingB = b['Currently Holding'] === 'Yes' ? 1 : 0;
            if (holdingA !== holdingB) return holdingB - holdingA;
            const pnlA = parseFloat(a['Total Realized PnL ($)']) || -Infinity;
            const pnlB = parseFloat(b['Total Realized PnL ($)']) || -Infinity;
            return pnlB - pnlA;
        });

        const tbody = document.querySelector(`#table-${prefix} tbody`);
        tbody.innerHTML = '';
        data.breakdown.forEach(row => {
            const tr = document.createElement('tr');
            
            // Format monetary values
            const pnl = row['Total Realized PnL ($)'] !== '' ? formatter.format(row['Total Realized PnL ($)']) : '';
            const cap = row['Deployed Capital ($)'] !== '' ? formatter.format(row['Deployed Capital ($)']) : '';
            
            // Apply green/red color to PnL
            let pnlStyle = '';
            if (row['Total Realized PnL ($)'] > 0) pnlStyle = 'color: #4CAF50;';
            else if (row['Total Realized PnL ($)'] < 0) pnlStyle = 'color: #ff4b4b;';

            tr.innerHTML = `
                <td>${row.Asset}</td>
                <td style="${pnlStyle}">${pnl}</td>
                <td>${cap}</td>
                <td>${row['Closed Trades']}</td>
                <td>${row['Win Rate']}</td>
                <td>${row['Currently Holding']}</td>
            `;
            tbody.appendChild(tr);
        });

        // Populate Live Portfolio Overview
        const allocContainer = document.getElementById(`allocations-${prefix}`);
        allocContainer.innerHTML = '';
        for (const [asset, amount] of Object.entries(data.allocations)) {
            const div = document.createElement('div');
            div.className = 'metric-card';
            div.style.minWidth = '150px';
            div.innerHTML = `
                <div class="metric-title">${asset}</div>
                <div class="metric-value">${formatter.format(amount)}</div>
            `;
            allocContainer.appendChild(div);
        }

        // Fetch and Render 30-Day Multi-Broker Race
        try {
            const raceRes = await fetch(`${API_BASE}/race?mode=${mode}`, { cache: 'no-store' });
            if (raceRes.ok) {
                const raceData = await raceRes.json();
                const raceTraces = [];
                for (const [persona, series] of Object.entries(raceData)) {
                    const t = {
                        x: series.dates,
                        y: series.values,
                        type: 'scatter',
                        mode: 'lines',
                        name: persona
                    };
                    if (persona.includes('Conservative')) { t.line = { dash: 'dot', color: '#FF851B', width: 4 }; }
                    else if (persona.includes('Neutral')) { t.line = { dash: 'dash', color: '#2ECC40', width: 4 }; }
                    else if (persona.includes('Balls')) { t.line = { color: '#00E5FF', width: 2 }; }
                    else if (persona.includes('SPY')) { t.line = { color: 'white', width: 2 }; }
                    else { t.line = { width: 2 }; } // Default Dynamic
                    raceTraces.push(t);
                }
                
                // Y-Axis Padding for Race Zoom
                let rMin = Infinity;
                let rMax = -Infinity;
                for (const series of Object.values(raceData)) {
                    const validVals = series.values.filter(v => v !== null);
                    if (validVals.length > 0) {
                        rMin = Math.min(rMin, ...validVals);
                        rMax = Math.max(rMax, ...validVals);
                    }
                }
                let rPad = Math.max((rMax - rMin) * 0.20, Math.abs(rMax) * 0.02);
                const firstDate = Object.values(raceData)[0].dates[0];
                const rAnchorTrace = {
                    x: [firstDate, firstDate],
                    y: [rMin - rPad, rMax + rPad],
                    mode: 'markers',
                    marker: { color: 'rgba(0,0,0,0)' },
                    showlegend: false,
                    hoverinfo: 'skip'
                };
                raceTraces.push(rAnchorTrace);
                
                const raceLayout = Object.assign({}, STD_LAYOUT, {
                    xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', rangeslider: { visible: true, thickness: 0.08, bgcolor: '#383838', bordercolor: '#1E90FF', borderwidth: 1 } },
                    yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' }
                });
                Plotly.newPlot(`race-${prefix}`, raceTraces, raceLayout);
            }
        } catch (e) {
            console.error("Failed to load race data", e);
        }
        
        await handleViewChange(prefix);

    } catch (error) {
        document.getElementById(`eq-${prefix}`).innerText = "N/A";
        document.getElementById(`ret-${prefix}`).innerText = "N/A";
        document.getElementById(`dd-${prefix}`).innerText = "N/A";
        document.getElementById(`sharpe-${prefix}`).innerText = "N/A";
        document.getElementById(`win-${prefix}`).innerText = "N/A";
        document.getElementById(`chart-${prefix}`).innerHTML = `<div style='color: red; text-align: left; margin-top: 20px; font-family: monospace;'><h3>UI Render Error:</h3><b>${error.message}</b><br><pre>${error.stack}</pre></div>`;
    }
}

// Tab Switching for Bayesian Tables
window.switchTableTab = function(prefix, tab, btnElement) {
    document.getElementById(`tbl-ai-${prefix}`).style.display = tab === 'ai' ? 'block' : 'none';
    document.getElementById(`tbl-broker-${prefix}`).style.display = tab === 'broker' ? 'block' : 'none';
    document.getElementById(`tbl-log-${prefix}`).style.display = tab === 'log' ? 'block' : 'none';
    
    const btns = document.getElementById(`bayesian-${prefix}`).querySelectorAll('.t-tab');
    btns.forEach(b => b.classList.remove('active'));
    if (btnElement) btnElement.classList.add('active');
};

function plotNormalDist(mu, sigma, targetDiv) {
    if (sigma <= 0) return;
    const x = [];
    const y = [];
    for (let i = mu - 4 * sigma; i <= mu + 4 * sigma; i += (8 * sigma) / 500) {
        x.push(i);
        const p = (1 / (sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * Math.pow((i - mu) / sigma, 2));
        y.push(p);
    }
    
    const xLoss = [], yLoss = [], xWin = [], yWin = [];
    for (let i=0; i<x.length; i++) {
        if (x[i] <= 0) { xLoss.push(x[i]); yLoss.push(y[i]); }
        if (x[i] >= 0) { xWin.push(x[i]); yWin.push(y[i]); }
    }
    
    const traceLoss = { x: xLoss, y: yLoss, fill: 'tozeroy', mode: 'none', fillcolor: 'rgba(255, 65, 54, 0.5)', name: 'Loss Region' };
    const traceWin = { x: xWin, y: yWin, fill: 'tozeroy', mode: 'none', fillcolor: 'rgba(46, 204, 64, 0.5)', name: 'Win Region' };
    
    Plotly.newPlot(targetDiv, [traceLoss, traceWin], Object.assign({}, STD_LAYOUT, {
        title: { text: 'Bayesian Probability Distribution', font: { color: 'white' }, y: 0.95 },
        margin: { t: 60, b: 40, l: 50, r: 10 },
        xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' },
        yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' }
    }));
}

async function handleViewChange(prefix) {
    const sel = document.getElementById(`view-${prefix}`);
    const ticker = sel.value;
    const mode = prefix === 'stocks' ? 'Single' : 'ETF';
    const persona = document.getElementById(`persona-${prefix}`).value;
    
    if (ticker === 'Portfolio Overview') {
        document.getElementById(`portfolio-overview-${prefix}`).style.display = 'block';
        document.getElementById(`bayesian-${prefix}`).style.display = 'none';
        return;
    }
    
    document.getElementById(`portfolio-overview-${prefix}`).style.display = 'none';
    document.getElementById(`bayesian-${prefix}`).style.display = 'block';
    
    try {
        const res = await fetch(`${API_BASE}/bayesian?ticker=${ticker}&persona=${persona}&mode=${mode}`, { cache: 'no-store' });
        if (!res.ok) throw new Error("Failed to load bayesian data");
        const data = await res.json();
        
        document.getElementById(`b-rec-${prefix}`).innerHTML = `Live Recommendation: <strong>${data.recommendation}</strong>`;
        document.getElementById(`b-prob-${prefix}`).innerText = `${(data.probability_up * 100).toFixed(1)}%`;
        document.getElementById(`b-ret-${prefix}`).innerText = `${(data.expected_return * 100).toFixed(2)}%`;
        document.getElementById(`b-sharpe-${prefix}`).innerText = data.expected_sharpe.toFixed(2);
        document.getElementById(`b-kelly-${prefix}`).innerText = `${(data.kelly_allocation * 100).toFixed(1)}%`;
        
        const noteEl = document.getElementById(`b-note-${prefix}`);
        if (data.broker_note && data.broker_note !== "nan" && data.broker_note !== "") {
            noteEl.innerText = data.broker_note;
            noteEl.style.color = "#FF4136";
        } else {
            noteEl.innerText = "Trade Cleared";
            noteEl.style.color = "#4CAF50";
        }
        
        plotNormalDist(data.expected_return, data.expected_risk, `chart-dist-${prefix}`);
        
        // Historical Prediction Line Chart
        if (data.history && data.history.length > 0) {
            const hDates = data.history.map(d => d.Date);
            const expRet = data.history.map(d => d['Expected Return %']);
            const actRet = data.history.map(d => d['Actual Daily Return %']);
            
            const trExp = { x: hDates, y: expRet, mode: 'lines', line: { color: '#FF851B', width: 2 }, name: 'Expected (Orange)' };
            const trAct = { x: hDates, y: actRet, mode: 'lines', line: { color: '#1E90FF', width: 2 }, name: 'Actual (Blue)' };
            
            let pMin = Math.min(...expRet, ...actRet);
            let pMax = Math.max(...expRet, ...actRet);
            let pPad = Math.max((pMax - pMin) * 0.20, Math.abs(pMax) * 0.02, 0.01);
            const trAnchor = { x: [hDates[0], hDates[0]], y: [pMin - pPad, pMax + pPad], mode: 'markers', marker: { color: 'rgba(0,0,0,0)' }, showlegend: false, hoverinfo: 'skip' };
            
            Plotly.newPlot(`chart-pred-${prefix}`, [trExp, trAct, trAnchor], Object.assign({}, STD_LAYOUT, {
                title: { text: 'Historical Predictions vs Actual Returns', font: { color: 'white' } },
                xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', rangeslider: { visible: true, thickness: 0.08, bgcolor: '#383838', bordercolor: '#1E90FF', borderwidth: 1 } },
                yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', tickformat: '.2%' }
            }));
            enableAutoYScale(`chart-pred-${prefix}`);
        } else {
            document.getElementById(`chart-pred-${prefix}`).innerHTML = "<p style='color: #94a3b8; text-align: center; margin-top: 100px;'>No prediction history.</p>";
        }
        
        const renderTbl = (id, rows) => {
            const tbl = document.getElementById(id).querySelector('table');
            let thead = tbl.querySelector('thead');
            let tbody = tbl.querySelector('tbody');
            if (!thead) { tbl.innerHTML = '<thead></thead><tbody></tbody>'; thead = tbl.querySelector('thead'); tbody = tbl.querySelector('tbody'); }
            if (rows.length === 0) {
                thead.innerHTML = '';
                tbody.innerHTML = '<tr><td style="text-align:center;">No data available.</td></tr>';
                return;
            }
            const keys = Object.keys(rows[0]);
            thead.innerHTML = `<tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr>`;
            tbody.innerHTML = rows.map(r => `<tr>${keys.map(k => {
                if (r[k] === 'CHECKBOX_TRUE') return `<td><input type="checkbox" checked disabled style="width: 15px; height: 15px;"></td>`;
                if (r[k] === 'CHECKBOX_FALSE') return `<td><input type="checkbox" disabled style="width: 15px; height: 15px;"></td>`;
                return `<td>${r[k] === null ? 'N/A' : r[k]}</td>`;
            }).join('')}</tr>`).join('');
        };
        renderTbl(`tbl-ai-${prefix}`, data.ai_ledger);
        renderTbl(`tbl-broker-${prefix}`, data.broker_ledger);
        
        // Populate Log
        const logHtml = data.recent_log && data.recent_log.length > 0 ? data.recent_log.map(l => `<p>${l}</p>`).join('') : "No recent trades detected.";
        document.getElementById(`log-content-${prefix}`).innerHTML = logHtml;
        
        // Single Ticker Race
        document.getElementById(`race-title-${prefix}`).innerText = `30-Day Race: ${ticker} Realized PnL`;
        const rt = [];
        let rMin = Infinity, rMax = -Infinity;
        for (const [p, series] of Object.entries(data.race_pnl)) {
            if (series.dates.length > 0) {
                const t = { x: series.dates, y: series.values, mode: 'lines+markers', name: p };
                if (p === 'Conservative') { t.line = { dash: 'dot', color: '#FF851B', width: 4 }; t.marker = { size: 8 }; }
                else if (p === 'Neutral') { t.line = { dash: 'dash', color: '#2ECC40', width: 4 }; }
                else { t.line = { color: '#00E5FF', width: 2 }; }
                rt.push(t);
                rMin = Math.min(rMin, ...series.values);
                rMax = Math.max(rMax, ...series.values);
            }
        }
        if (rt.length > 0) {
            let rPad = Math.max((rMax - rMin) * 0.20, Math.abs(rMax) * 0.02);
            const rAnchor = { x: [rt[0].x[0], rt[0].x[0]], y: [rMin - rPad, rMax + rPad], mode: 'markers', marker: { color: 'rgba(0,0,0,0)' }, showlegend: false, hoverinfo: 'skip' };
            rt.push(rAnchor);
            Plotly.newPlot(`chart-single-race-${prefix}`, rt, Object.assign({}, STD_LAYOUT, {
                xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', rangeslider: { visible: true, thickness: 0.08, bgcolor: '#383838', bordercolor: '#1E90FF', borderwidth: 1 } },
                yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' }
            }));
            enableAutoYScale(`chart-single-race-${prefix}`);
        }
        
    } catch (e) {
        console.error(e);
    }
}

let olympicTimer = null;

async function loadOlympic() {
    try {
        const res = await fetch(`${API_BASE}/olympic`, { cache: 'no-store' });
        if (!res.ok) throw new Error("Olympic data not available");
        const data = await res.json();
        
        // 1. Countdown Timer
        const targetDate = new Date(data.eta_timestamp);
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' };
        document.getElementById('oly-date').innerText = `📅 ${targetDate.toLocaleDateString('en-US', options)}`;
        
        if (olympicTimer) clearInterval(olympicTimer);
        olympicTimer = setInterval(() => {
            const now = new Date().getTime();
            const distance = targetDate.getTime() - now;
            if (distance < 0) {
                clearInterval(olympicTimer);
                document.getElementById('oly-timer').innerText = "0h 0m 0s (Running...)";
            } else {
                const days = Math.floor(distance / (1000 * 60 * 60 * 24));
                const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((distance % (1000 * 60)) / 1000);
                document.getElementById('oly-timer').innerText = `${days > 0 ? days + 'd ' : ''}${hours}h ${minutes}m ${seconds}s`;
            }
        }, 1000);
        
        // 2. Metrics
        document.getElementById('o-ret-cap').innerText = `${data.metrics.EL_CAP.return > 0 ? '+' : ''}${data.metrics.EL_CAP.return.toFixed(2)}%`;
        document.getElementById('o-dd-cap').innerText = `Max DD: ${data.metrics.EL_CAP.dd.toFixed(2)}%`;
        document.getElementById('o-ret-vol').innerText = `${data.metrics.EL_VOLTI.return > 0 ? '+' : ''}${data.metrics.EL_VOLTI.return.toFixed(2)}%`;
        document.getElementById('o-dd-vol').innerText = `Max DD: ${data.metrics.EL_VOLTI.dd.toFixed(2)}%`;
        document.getElementById('o-ret-champ').innerText = `${data.metrics.CHAMPION.return > 0 ? '+' : ''}${data.metrics.CHAMPION.return.toFixed(2)}%`;
        document.getElementById('o-dd-champ').innerText = `Max DD: ${data.metrics.CHAMPION.dd.toFixed(2)}%`;
        
        // 3. Race Chart
        const getMedal = r => r === 1 ? ' 🏅' : (r === 2 ? ' 🥈' : (r === 3 ? ' 🥉' : ''));
        const nCap = `EL_CAP (Liquidity)${getMedal(data.metrics.EL_CAP.rank)}`;
        const nVol = `EL_VOLTI (Stability)${getMedal(data.metrics.EL_VOLTI.rank)}`;
        const nChamp = `CHAMPION (VIP)${getMedal(data.metrics.CHAMPION.rank)}`;
        
        const trCap = { x: data.chart_data.dates, y: data.chart_data.EL_CAP, mode: 'lines', line: { dash: 'dot', color: '#FF851B', width: 8 }, name: nCap };
        const trVol = { x: data.chart_data.dates, y: data.chart_data.EL_VOLTI, mode: 'lines', line: { dash: 'dash', color: '#2ECC40', width: 5 }, name: nVol };
        const trChamp = { x: data.chart_data.dates, y: data.chart_data.CHAMPION, mode: 'lines+markers', marker: { size: 6 }, line: { color: '#00E5FF', width: 2 }, name: nChamp };
        
        let rMin = Math.min(...data.chart_data.EL_CAP, ...data.chart_data.EL_VOLTI, ...data.chart_data.CHAMPION);
        let rMax = Math.max(...data.chart_data.EL_CAP, ...data.chart_data.EL_VOLTI, ...data.chart_data.CHAMPION);
        let rPad = Math.max((rMax - rMin) * 0.20, Math.abs(rMax) * 0.02);
        const rAnchor = { x: [data.chart_data.dates[0], data.chart_data.dates[0]], y: [rMin - rPad, rMax + rPad], mode: 'markers', marker: { color: 'rgba(0,0,0,0)' }, showlegend: false, hoverinfo: 'skip' };
        
        Plotly.newPlot('chart-olympic-race', [trCap, trVol, trChamp, rAnchor], Object.assign({}, STD_LAYOUT, {
            xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', rangeslider: { visible: true, thickness: 0.08, bgcolor: '#383838', bordercolor: '#1E90FF', borderwidth: 1 } },
            yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', tickformat: '$.2f' }
        }));
        enableAutoYScale('chart-olympic-race');
        
        // 4. Data Table
        const tbl = document.getElementById('tbl-olympic');
        if (data.table_data.length > 0) {
            const keys = Object.keys(data.table_data[0]);
            tbl.querySelector('thead').innerHTML = `<tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr>`;
            tbl.querySelector('tbody').innerHTML = data.table_data.map(r => `<tr>${keys.map(k => `<td>${r[k]}</td>`).join('')}</tr>`).join('');
        }
    } catch (e) {
        console.error("Olympic load error:", e);
    }
}

async function loadAutopsy() {
    try {
        const res = await fetch(`${API_BASE}/autopsy`, { cache: 'no-store' });
        if (!res.ok) throw new Error("Autopsy data not available");
        const data = await res.json();
        
        function renderAutopsySection(sectionData, prefix, color1, color2) {
            // 1. Serial Offenders Bar Chart
            if (sectionData.serial_offenders.length > 0) {
                const trOffenders = {
                    x: sectionData.serial_offenders.map(d => d.Ticker),
                    y: sectionData.serial_offenders.map(d => d.Loss),
                    type: 'bar',
                    marker: { color: color1 },
                    showlegend: false,
                    width: 0.4
                };
                Plotly.newPlot(`chart-autopsy-serial-${prefix}`, [trOffenders], Object.assign({}, STD_LAYOUT, {
                    title: { text: 'Top 10 Serial Offenders (Total Loss $)', font: { color: 'white' } },
                    xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' },
                    yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', tickformat: '$.2f' },
                    bargap: 0.8
                }));
            }
            
            // 2. Day Vulnerability Bar Chart
            if (sectionData.day_vulnerability.length > 0) {
                const trDays = {
                    x: sectionData.day_vulnerability.map(d => d.Day),
                    y: sectionData.day_vulnerability.map(d => d.Loss),
                    type: 'bar',
                    marker: { color: color2 },
                    showlegend: false,
                    width: 0.4
                };
                Plotly.newPlot(`chart-autopsy-day-${prefix}`, [trDays], Object.assign({}, STD_LAYOUT, {
                    title: { text: 'Vulnerability by Day of Week', font: { color: 'white' } },
                    xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' },
                    yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', tickformat: '$.2f' },
                    bargap: 0.8
                }));
            }
            
            // 3. Forensic Ledger
            const tbl = document.getElementById(`tbl-autopsy-${prefix}`);
            if (sectionData.forensic_ledger.length > 0) {
                const keys = Object.keys(sectionData.forensic_ledger[0]);
                tbl.querySelector('thead').innerHTML = `<tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr>`;
                tbl.querySelector('tbody').innerHTML = sectionData.forensic_ledger.map(r => `<tr>${keys.map(k => `<td>${r[k]}</td>`).join('')}</tr>`).join('');
            } else {
                document.getElementById(`chart-autopsy-serial-${prefix}`).style.display = 'none';
                document.getElementById(`chart-autopsy-day-${prefix}`).style.display = 'none';
                tbl.innerHTML = "<tr><td style='text-align:center;'>No capitalized losses found in recent ledger! ✅</td></tr>";
            }
        }
        
        if(data.stock) renderAutopsySection(data.stock, 'stock', '#FF4136', '#85144b');
        if(data.etf) renderAutopsySection(data.etf, 'etf', '#a371f7', '#6f42c1');
        
    } catch (e) {
        console.error("Autopsy load error:", e);
    }
}


async function loadProdShadow() {
    try {
        const res = await fetch(`${API_BASE}/prod_shadow`, { cache: 'no-store' });
        if (!res.ok) throw new Error("Prod vs Shadow data not available");
        const data = await res.json();
        
        if (data.dates.length === 0) return;

        // --- INJECT PNL INTO DOM BOXES ---
        const lastProd = data.prod[data.prod.length - 1];
        const lastTrans = data.trans[data.trans.length - 1];
        const lastV1 = data.v1[data.v1.length - 1];
        const lastLstm = data.lstm[data.lstm.length - 1];
        
        const formatMoney = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
        const formatPnL = (val) => {
            const pnl = val - 10000;
            const sign = pnl >= 0 ? '+' : '';
            const color = pnl >= 0 ? '#32CD32' : '#FF4136';
            return `${formatMoney(val)} <span style="color:${color}; font-size:12px;">(${sign}${formatMoney(pnl)})</span>`;
        };
        
        if(document.getElementById('pnl-box-prod')) document.getElementById('pnl-box-prod').innerHTML = formatPnL(lastProd);
        if(document.getElementById('pnl-box-trans')) document.getElementById('pnl-box-trans').innerHTML = formatPnL(lastTrans);
        if(document.getElementById('pnl-box-v1')) document.getElementById('pnl-box-v1').innerHTML = formatPnL(lastV1);
        if(document.getElementById('pnl-box-lstm')) document.getElementById('pnl-box-lstm').innerHTML = formatPnL(lastLstm);
        // ----------------------------------

        const trProd = { x: data.dates, y: data.prod, name: 'Prod (BallsForBrains)', mode: 'lines', line: { color: '#32CD32', width: 4 } };
        const trTrans = { x: data.dates, y: data.trans, name: 'Shadow Transformer', mode: 'lines', line: { color: '#FF4136', width: 3, dash: 'dot' } };
        const trV1 = { x: data.dates, y: data.v1, name: 'Sandbox V1 Classic', mode: 'lines', line: { color: '#87CEEB', width: 3, dash: 'dash' } };
        const trLstm = { x: data.dates, y: data.lstm, name: 'Shadow LSTM', mode: 'lines', line: { color: '#FF00FF', width: 3, dash: 'dashdot' } };
        
        Plotly.newPlot('chart-prod-shadow', [trProd, trTrans, trV1, trLstm], Object.assign({}, STD_LAYOUT, {
            xaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)' },
            yaxis: { color: 'white', gridcolor: 'rgba(255,255,255,0.1)', tickformat: '$.2f' },
            title: { text: "Performance Race: Prod vs Shadows", font: { color: 'white' } }
        }));
        
        const tbl = document.getElementById('tbl-prodshadow');
        if (data.table.length > 0) {
            const keys = Object.keys(data.table[0]);
            tbl.querySelector('thead').innerHTML = `<tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr>`;
            tbl.querySelector('tbody').innerHTML = data.table.map(r => `<tr>${keys.map(k => `<td>${r[k]}</td>`).join('')}</tr>`).join('');
        }
    } catch (e) {
        console.error("Prod vs Shadow load error:", e);
    }
}
