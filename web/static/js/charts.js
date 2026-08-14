/**
 * charts.js - 数据可视化（Canvas 2D 绘图）
 * 会话概览、概率状态 + 自动刷新 & 变化高亮
 * 刷新策略：首次/会话切换时重建 DOM，后续自动刷新时原地更新数据（无闪烁）
 */

const Charts = {
    _session: '',
    _refreshTimer: null,
    _autoRefresh: true,
    _prevData: {},  // 上一次各图表数据，用于变化检测
    _initialized: false, // 当前 grid 是否已渲染过结构

    /** 初始化图表视图 */
    async init() {
        this._prevData = {};
        this._session = '';
        this._initialized = false;
        await this._loadSessions();
        this._bindEvents();
        this._setupAutoRefresh();
        await this._loadCharts(true);
        this._bindThemeChange();
    },

    /** 监听主题切换，立即重绘 canvas 图表（颜色依赖 CSS 变量） */
    _bindThemeChange() {
        if (this._themeBound) return;
        this._themeBound = true;
        window.addEventListener('themeChanged', () => {
            if (this._initialized) this._loadCharts(false);
        });
    },

    /** 销毁（切换视图时调用） */
    destroy() {
        if (this._refreshTimer) { clearInterval(this._refreshTimer); this._refreshTimer = null; }
        this._initialized = false;
        this._themeBound = false;
    },

    /** 设置自动刷新 */
    _setupAutoRefresh() {
        if (this._refreshTimer) clearInterval(this._refreshTimer);
        if (this._autoRefresh) {
            this._refreshTimer = setInterval(() => {
                this._loadCharts(false);
            }, 3000);
        }
    },

    /** 加载会话列表到下拉框 */
    async _loadSessions() {
        const select = document.getElementById('chart-session-select');
        if (!select) return;
        const res = await Api.dataSessions();
        const prevVal = this._session;
        select.innerHTML = '<option value="">选择会话...</option>';
        if (res.ok && res.sessions) {
            res.sessions.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = s;
                select.appendChild(opt);
            });
        }
        // 恢复之前的选择（若仍在列表中）
        if (prevVal && select.querySelector(`option[value="${CSS.escape(prevVal)}"]`)) {
            select.value = prevVal;
            this._session = prevVal;
        } else {
            this._session = '';
        }
    },

    /** 绑定事件 */
    _bindEvents() {
        const select = document.getElementById('chart-session-select');
        const refreshBtn = document.getElementById('btn-refresh-charts');

        if (select && !select._chartsBound) {
            select._chartsBound = true;
            select.addEventListener('change', () => {
                this._session = select.value;
                this._prevData = {};
                this._initialized = false;
                this._loadCharts(true);
            });
        }

        // 手动刷新按钮（始终可用，无会话时只刷新全局概览）
        if (refreshBtn && !refreshBtn._chartsBound) {
            refreshBtn._chartsBound = true;
            refreshBtn.addEventListener('click', async () => {
                refreshBtn.disabled = true;
                refreshBtn.textContent = '刷新中...';
                try {
                    this._initialized = false;
                    await this._loadCharts(true);
                    Utils.toast('数据已刷新', 'success', 2000);
                } catch (e) {
                    Utils.toast('刷新失败', 'error', 3000);
                } finally {
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = '🔄 刷新';
                }
            });
        }

        // 自动刷新开关
        const toggle = document.getElementById('charts-auto-refresh');
        if (toggle && !toggle._bound) {
            toggle._bound = true;
            toggle.addEventListener('change', (e) => {
                this._autoRefresh = e.target.checked;
                const dot = document.getElementById('charts-refresh-dot');
                if (dot) dot.className = 'dot' + (this._autoRefresh ? ' active' : '');
                this._setupAutoRefresh();
            });
        }
    },

    /**
     * 加载所有图表数据
     * @param {boolean} rebuild - true=重建DOM结构（首次/会话切换），false=原地更新数值（自动刷新）
     */
    async _loadCharts(rebuild = false) {
        const grid = document.getElementById('charts-grid');
        if (!grid) return;

        // 首次或会话切换：重建整个 DOM 结构
        if (rebuild || !this._initialized) {
            grid.innerHTML = '<div class="chart-empty" style="grid-column:1/-1;padding:40px;">加载中...</div>';

            if (!this._session) {
                grid.innerHTML = '';
                await this._buildOverview(grid);
                grid.innerHTML += '<div class="chart-empty" style="grid-column:1/-1;padding:40px;">请选择一个会话查看详细数据</div>';
                this._initialized = true;
                return;
            }

            const [overviewRes, probRes, detailRes] = await Promise.allSettled([
                Api.dataOverview(),
                Api.dataProbability(this._session),
                Api.sessionDetail(this._session),
            ]);

            grid.innerHTML = '';
            await this._buildOverview(grid, overviewRes.value, detailRes.value);
            await this._buildProbability(grid, probRes.value);
            this._initialized = true;
            return;
        }

        // 自动刷新：原地更新，不重建 DOM，不产生闪烁
        // 无会话时仅刷新全局概览，避免无效 API 调用
        if (this._session) {
            const [overviewRes, probRes, detailRes] = await Promise.allSettled([
                Api.dataOverview({ autoRefresh: true }),
                Api.dataProbability(this._session, { autoRefresh: true }),
                Api.sessionDetail(this._session, { autoRefresh: true }),
            ]);
            this._updateOverview(overviewRes.value, detailRes.value);
            this._updateProbability(probRes.value);
        } else {
            const overviewRes = await Api.dataOverview({ autoRefresh: true });
            this._updateOverview(overviewRes, null);
        }
    },

    // ==================== 构建（首次渲染）====================

    /** 总览卡片（构建） */
    async _buildOverview(grid, res, detailRes) {
        try {
            if (!res) res = await Api.dataOverview();
            if (!res || !res.ok) return;
            const d = res.overview || {};
            const sd = (detailRes && detailRes.ok) ? (detailRes.detail || {}) : {};

            const overview = document.createElement('div');
            overview.className = 'overview-grid';
            overview.id = 'overview-grid';
            overview.style.gridColumn = '1 / -1';

            const cards = [
                { label: '活跃会话', value: d.total_sessions || 0, id: 'ov-total-sessions' },
                { label: '处理中', value: sd.is_processing !== undefined ? (sd.is_processing ? '是' : '否') : (d.active_processing || 0), id: 'ov-processing' },
                { label: '缓存消息', value: sd.message_cache_count ?? d.total_cached_messages ?? 0, id: 'ov-cached-msgs' },
            ];

            cards.forEach(c => {
                const card = document.createElement('div');
                card.className = 'overview-card';
                card.id = c.id;
                card.innerHTML = `<div class="stat-value" id="${c.id}-val">${c.value}</div>
                    <div class="stat-label">${c.label}</div>`;
                this._prevData[c.id] = c.value;
                overview.appendChild(card);
            });

            grid.appendChild(overview);
        } catch (e) {
            console.error('Charts: overview build failed', e);
        }
    },

    /** 概率状态（构建） */
    async _buildProbability(grid, res) {
        try {
            if (!res) res = await Api.dataProbability(this._session);
            const { card, canvas, wrap } = this._createCard(
                '概率状态', { cls: 'live', text: '实时' }, grid, 'chart-probability'
            );

            const d = res && res.ok ? (res.probability || {}) : {};
            if (!Object.keys(d).length) {
                wrap.innerHTML = '<div class="chart-empty">暂无概率数据</div>';
                return;
            }

            const { labels, values } = this._probLabelsValues(d);
            const modeNote = document.createElement('div');
            modeNote.style.cssText = 'font-size:12px;color:var(--text-secondary);margin-bottom:10px;line-height:1.6;';
            modeNote.innerHTML = `当前为<strong>传统模式</strong>：回复后概率提升按整个会话计算，持续 <strong>${d.probability_duration || 0}s</strong>，再次成功回复会刷新计时。`;
            card.appendChild(modeNote);
            this._drawBarChart(canvas, labels, values, 'var(--accent-red)');

            const stats = document.createElement('div');
            stats.className = 'stats-row';
            stats.id = 'stats-probability';
            stats.innerHTML = `
                <div class="stat-item"><div class="stat-value" id="prob-init">${((d.initial_probability || 0) * 100).toFixed(1)}%</div><div class="stat-label">基础概率</div></div>
                <div class="stat-item"><div class="stat-value" id="prob-reply">${((d.after_reply_probability || 0) * 100).toFixed(1)}%</div><div class="stat-label">回复后概率</div></div>
                <div class="stat-item"><div class="stat-value" id="prob-mode">传统模式</div><div class="stat-label">当前模式</div></div>`;
            card.appendChild(stats);

            this._prevData['prob-data'] = values.join(',');
        } catch (e) {
            console.error('Charts: probability build failed', e);
        }
    },

    // ==================== 原地更新（自动刷新）====================

    /** 总览更新（只改数字，触发变化高亮） */
    _updateOverview(res, detailRes) {
        if (!res || !res.ok) return;
        const d = res.overview || {};
        const sd = (detailRes && detailRes.ok) ? (detailRes.detail || {}) : {};
        const map = {
            'ov-total-sessions': d.total_sessions || 0,
            'ov-processing': sd.is_processing !== undefined ? (sd.is_processing ? '是' : '否') : (d.active_processing || 0),
            'ov-cached-msgs': sd.message_cache_count ?? d.total_cached_messages ?? 0,
        };
        for (const [id, val] of Object.entries(map)) {
            const valEl = document.getElementById(`${id}-val`);
            if (!valEl) continue;
            if (this._prevData[id] !== val) {
                valEl.textContent = val;
                Utils.highlightChange(document.getElementById(id));
                this._prevData[id] = val;
            }
        }
    },

    /** 概率更新 */
    _updateProbability(res) {
        try {
            const d = res && res.ok ? (res.probability || {}) : {};
            if (!Object.keys(d).length) return;

            const { labels, values } = this._probLabelsValues(d);
            const key = values.join(',');
            const canvas = document.querySelector('#chart-probability canvas');
            if (canvas) {
                this._drawBarChart(canvas, labels, values, 'var(--accent-red)');
                this._prevData['prob-data'] = key;
            }

            const initVal = ((d.initial_probability || 0) * 100).toFixed(1) + '%';
            const replyVal = ((d.after_reply_probability || 0) * 100).toFixed(1) + '%';
            this._setTextIfChanged('prob-init', initVal);
            this._setTextIfChanged('prob-reply', replyVal);
            this._setTextIfChanged('prob-mode', '传统模式');
        } catch (e) { console.error('Charts: probability update failed', e); }
    },

    // ==================== 辅助方法 ====================

    /** 更新文字（有变化时高亮） */
    _setTextIfChanged(id, newVal) {
        const el = document.getElementById(id);
        if (!el) return;
        const newStr = String(newVal);
        if (el.textContent !== newStr) {
            el.textContent = newStr;
            Utils.highlightChange(el.closest('.stat-item') || el);
        }
    },

    /** 提取概率图的 labels/values */
    _probLabelsValues(d) {
        const labels = ['基础概率'];
        const values = [d.initial_probability || 0];
        labels.push('回复后概率');
        values.push(d.after_reply_probability || 0);
        return { labels, values };
    },

    /** 创建图表卡片骨架，cardId 用于原地更新时定位 canvas */
    _createCard(title, badge, grid, cardId) {
        const card = document.createElement('div');
        card.className = 'chart-card';
        if (cardId) card.id = cardId;
        const header = document.createElement('div');
        header.className = 'chart-card-header';
        header.innerHTML = `<span class="chart-card-title">${title}</span>
            <span class="chart-card-badge ${badge.cls}">${badge.text}</span>`;
        card.appendChild(header);

        const wrap = document.createElement('div');
        wrap.className = 'chart-canvas-wrap';
        const canvas = document.createElement('canvas');
        wrap.appendChild(canvas);
        card.appendChild(wrap);

        grid.appendChild(card);
        return { card, canvas, wrap };
    },

    /** Canvas 柱状图绘制 */
    _drawBarChart(canvas, labels, values, color) {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = rect.height + 'px';

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        const w = rect.width, h = rect.height;
        const pad = { top: 22, right: 10, bottom: 40, left: 50 };
        const chartW = w - pad.left - pad.right;
        const chartH = h - pad.top - pad.bottom;

        if (!values.length) return;
        const max = Math.max(...values, 0.01);

        const style = getComputedStyle(document.documentElement);
        const resolveColor = c => {
            if (c.startsWith('var(')) {
                const varName = c.slice(4, -1).trim();
                return style.getPropertyValue(varName).trim() || '#e02020';
            }
            return c;
        };
        const barColor = resolveColor(color);
        const textMuted = style.getPropertyValue('--text-muted').trim() || '#555555';
        const textPrimary = style.getPropertyValue('--text-primary').trim() || '#f0f0f0';
        const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        const gridLineColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.08)';

        // 网格线
        ctx.strokeStyle = gridLineColor;
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = pad.top + chartH * (1 - i / 4);
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(pad.left + chartW, y);
            ctx.stroke();

            ctx.fillStyle = textMuted;
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'right';
            const v = (max * i / 4).toFixed(max < 1 ? 2 : 0);
            ctx.fillText(v, pad.left - 6, y + 3);
        }

        // 柱子
        const barW = Math.min(40, chartW / labels.length * 0.6);
        const gap = chartW / labels.length;
        const barRects = [];

        labels.forEach((label, i) => {
            const x = pad.left + gap * i + (gap - barW) / 2;
            const barH = (values[i] / max) * chartH;
            const y = pad.top + chartH - barH;

            ctx.fillStyle = barColor;
            ctx.globalAlpha = 0.85;
            ctx.beginPath();
            ctx.roundRect(x, y, barW, barH, [3, 3, 0, 0]);
            ctx.fill();
            ctx.globalAlpha = 1;

            // X 轴标签
            ctx.fillStyle = textMuted;
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            const tl = label.length > 6 ? label.slice(0, 6) + '..' : label;
            ctx.fillText(tl, pad.left + gap * i + gap / 2, h - pad.bottom + 16);

            // 值标签
            ctx.fillStyle = textPrimary;
            ctx.font = '11px sans-serif';
            const vt = values[i] < 1 ? values[i].toFixed(2) : String(Math.round(values[i]));
            ctx.fillText(vt, pad.left + gap * i + gap / 2, y - 4);

            barRects.push({ x, w: barW, label });
        });

        // 存储柱位置用于 tooltip 碰撞检测
        canvas._barRects = barRects;
        this._ensureTooltip(canvas);
    },

    /** 为柱状图 canvas 绑定 tooltip（hover + touch，仅绑一次） */
    _ensureTooltip(canvas) {
        if (canvas._tooltipBound) return;
        canvas._tooltipBound = true;

        const wrap = canvas.parentElement;
        let tooltip = wrap.querySelector('.chart-tooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.className = 'chart-tooltip';
            tooltip.style.cssText =
                'position:absolute;z-index:50;padding:4px 8px;background:var(--bg-card);' +
                'color:var(--text-primary);font-size:11px;font-family:monospace;' +
                'border:1px solid var(--border-color);border-radius:4px;' +
                'pointer-events:none;white-space:nowrap;display:none;' +
                'box-shadow:0 2px 8px rgba(0,0,0,0.35);';
            wrap.appendChild(tooltip);
        }

        const showAt = (clientX, clientY, text) => {
            const wr = wrap.getBoundingClientRect();
            tooltip.textContent = text;
            let left = clientX - wr.left - tooltip.offsetWidth / 2;
            left = Math.max(4, Math.min(left, wr.width - tooltip.offsetWidth - 4));
            tooltip.style.left = left + 'px';
            tooltip.style.top = Math.max(0, clientY - wr.top - 32) + 'px';
            tooltip.style.display = 'block';
        };

        const hide = () => { tooltip.style.display = 'none'; };

        const hitTest = (clientX, clientY) => {
            const cr = canvas.getBoundingClientRect();
            const mx = clientX - cr.left;
            for (const r of canvas._barRects || []) {
                if (mx >= r.x && mx <= r.x + r.w) return r;
            }
            return null;
        };

        canvas.addEventListener('mousemove', (e) => {
            const hit = hitTest(e.clientX, e.clientY);
            hit ? showAt(e.clientX, e.clientY, hit.label) : hide();
        });
        canvas.addEventListener('mouseleave', hide);

        // 触摸：点击柱区域显示，点空白/外部消失
        let _touchActive = false;
        canvas.addEventListener('click', (e) => {
            const hit = hitTest(e.clientX, e.clientY);
            if (hit) {
                _touchActive = true;
                showAt(e.clientX, e.clientY, hit.label);
                e.stopPropagation();
            } else {
                _touchActive = false;
                hide();
            }
        });
        document.addEventListener('click', (ev) => {
            if (_touchActive && ev.target !== canvas) { _touchActive = false; hide(); }
        }, true);
    }
};
