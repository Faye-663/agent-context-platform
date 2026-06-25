/* ACP MCP Playground - app.js */

const McpClient = {
  serverUrl: '',

  async listTools(url) {
    const requestBody = { jsonrpc: '2.0', id: 1, method: 'tools/list' };
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
    const responseBody = await resp.json();
    if (responseBody.error) throw new Error(responseBody.error.message || 'tools/list failed');
    return responseBody.result.tools || [];
  },

  async callTool(url, name, args) {
    const requestBody = {
      jsonrpc: '2.0', id: Date.now(), method: 'tools/call',
      params: { name, arguments: args },
    };
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
    const responseBody = await resp.json();
    if (responseBody.error) throw new Error(responseBody.error.message || 'tools/call failed');
    if (responseBody.result.content[0]?.text) {
      try {
        return {
          wire: { request: requestBody, response: responseBody },
          result: JSON.parse(responseBody.result.content[0].text),
        };
      }
      catch (e) { throw new Error('Failed to parse tool response: ' + e.message); }
    }
    return { wire: { request: requestBody, response: responseBody }, result: responseBody.result };
  },
};


const App = {
  tools: [],
  selectedTool: null,

  init() {
    document.getElementById('btn-connect').onclick = () => this.connect();
    document.getElementById('btn-invoke').onclick = () => this.invoke();
    document.getElementById('include-trace').onchange = () => this.updateDebugOptions();

    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.onclick = () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById(tab + '-response').classList.add('active');
      };
    });
  },

  async connect() {
    const url = document.getElementById('server-url').value.trim();
    if (!url) return;
    const status = document.getElementById('status-indicator');
    status.textContent = '连接中...';
    status.className = '';
    try {
      this.tools = await McpClient.listTools(url);
      McpClient.serverUrl = url;
      status.textContent = '已连接 (' + this.tools.length + ' tools)';
      status.className = 'connected';
      this.renderTools();
      document.getElementById('btn-invoke').disabled = false;
    } catch (e) {
      status.textContent = '连接失败: ' + e.message;
      status.className = 'disconnected';
    }
  },

  renderTools() {
    const ul = document.getElementById('tools');
    ul.replaceChildren();
    this.tools.forEach(t => {
      const li = document.createElement('li');
      li.dataset.toolName = t.name;
      const name = document.createElement('span');
      name.className = 'tool-name';
      name.textContent = t.name;
      li.appendChild(name);
      li.onclick = () => this.selectTool(t);
      ul.appendChild(li);
    });
  },

  selectTool(tool) {
    document.querySelectorAll('#tools li').forEach(l => l.classList.remove('active'));
    document.querySelectorAll('#tools li').forEach(li => {
      if (li.dataset.toolName === tool.name) li.classList.add('active');
    });
    this.selectedTool = tool;
    document.getElementById('selected-tool-name').textContent = tool.name;
    document.getElementById('selected-tool-desc').textContent = tool.description || '';

    const form = document.getElementById('param-form');
    form.replaceChildren();
    const schema = tool.inputSchema;
    if (schema && schema.properties) {
      Object.entries(schema.properties).forEach(([key, prop]) => {
        const label = document.createElement('label');
        label.textContent = key + (schema.required && schema.required.includes(key) ? ' *' : '');
        form.appendChild(label);
        if (prop.type === 'object' || prop.type === 'array') {
          const ta = document.createElement('textarea');
          ta.dataset.param = key;
          ta.rows = prop.type === 'array' ? 4 : 3;
          ta.placeholder = prop.type === 'array' ? '[]' : '{}';
          form.appendChild(ta);
        } else {
          const input = document.createElement('input');
          input.type = prop.type === 'number' ? 'number' : 'text';
          input.dataset.param = key;
          if (prop.default !== undefined) input.value = prop.default;
          input.placeholder = prop.description || '';
          form.appendChild(input);
        }
      });
    }
    // Hide debug options for tools that don't support it
    document.getElementById('debug-options').style.display =
      ['search_code','search_db_schema','search_doc','build_task_context'].includes(tool.name) ? '' : 'none';
  },

  updateDebugOptions() { /* handled in invoke */ },

  async invoke() {
    if (!this.selectedTool) return;
    const args = {};
    document.querySelectorAll('#param-form [data-param]').forEach(el => {
      const val = el.value.trim();
      if (!val) return;
      try {
        args[el.dataset.param] = (el.tagName === 'TEXTAREA') ? JSON.parse(val) :
          (el.type === 'number') ? Number(val) : val;
      } catch {
        args[el.dataset.param] = val;
      }
    });

    if (document.getElementById('include-trace').checked) {
      args.debug_options = args.debug_options || {};
      args.debug_options.include_trace = true;
    }

    try {
      const response = await McpClient.callTool(McpClient.serverUrl, this.selectedTool.name, args);
      this.renderResponse(response.result, response.wire);
    } catch (e) {
      this.renderJson(document.getElementById('raw-response'), { error: String(e.message) }, 'error-response');
      document.getElementById('readable-response').replaceChildren();
      document.getElementById('trace-panel').classList.add('collapsed');
    }
  },

  renderResponse(data, wire) {
    this.renderJson(document.getElementById('raw-response'), wire);

    const readable = document.getElementById('readable-response');
    const toolName = this.selectedTool.name;
    readable.replaceChildren();

    if (toolName === 'build_task_context') {
      this.renderTaskContext(data, readable);
    } else if (toolName === 'search_code' || toolName === 'search_db_schema' || toolName === 'search_doc') {
      this.renderSearchResults(data, readable);
    }

    // Trace
    const tracePanel = document.getElementById('trace-panel');
    if (data._trace) {
      this.renderJson(document.getElementById('trace-content'), data._trace);
      tracePanel.classList.remove('collapsed');
    } else {
      tracePanel.classList.add('collapsed');
    }
  },

  renderSearchResults(data, container) {
    const results = data.results || [];
    if (!results.length) {
      this.appendText(container, 'p', 'No results.');
      return;
    }
    results.forEach((r, i) => {
      const item = r.item || {};
      const src = r.source || {};
      const card = document.createElement('div');
      card.className = 'result-card';
      const header = document.createElement('div');
      header.className = 'result-header';
      this.appendText(header, 'span', '#' + (i + 1) + ' Score: ' + (r.score || 0).toFixed(4), 'result-score');
      card.appendChild(header);
      this.appendText(card, 'div', item.title || item.id || '-', 'result-title');
      this.appendText(card, 'div', r.match_reason || '', 'result-reason');
      if (src.path) {
        const lineRange = src.start_line ? ':' + src.start_line + '-' + src.end_line : '';
        this.appendText(card, 'div', src.path + lineRange, 'result-path');
      }
      if (r.score_parts) {
        const scoreParts = document.createElement('div');
        scoreParts.className = 'score-parts';
        Object.entries(r.score_parts).forEach(([k, v]) => {
          if (v > 0) this.appendText(scoreParts, 'span', k + ': ' + v.toFixed(4), 'score-part');
        });
        card.appendChild(scoreParts);
      }
      container.appendChild(card);
    });
  },

  renderTaskContext(data, container) {
    const groups = ['related_code', 'related_db_schema', 'related_docs', 'similar_implementations'];
    const labels = { related_code: 'Code', related_db_schema: 'DB Schema', related_docs: 'Docs', similar_implementations: 'Similar' };

    // Risks & missing
    const alerts = document.createElement('div');
    (data.risks || []).forEach(r => {
      const span = document.createElement('span'); span.className = 'risk-badge'; span.textContent = r; alerts.appendChild(span);
    });
    (data.missing_context || []).forEach(m => {
      const span = document.createElement('span'); span.className = 'missing-badge'; span.textContent = 'missing: ' + m; alerts.appendChild(span);
    });
    container.appendChild(alerts);

    // Tabs
    const tabBar = document.createElement('div');
    tabBar.className = 'context-tabs';
    const tabContents = {};
    groups.forEach((g, i) => {
      const tab = document.createElement('button');
      tab.className = 'context-tab' + (i === 0 ? ' active' : '');
      tab.textContent = labels[g] + ' (' + (data[g] || []).length + ')';
      tab.onclick = () => {
        tabBar.querySelectorAll('.context-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        Object.values(tabContents).forEach(c => c.classList.remove('active'));
        tabContents[g].classList.add('active');
      };
      tabBar.appendChild(tab);

      const content = document.createElement('div');
      content.className = 'context-tab-content' + (i === 0 ? ' active' : '');
      if (data[g] && data[g].length) {
        this.renderSearchResults({ results: data[g] }, content);
      } else {
        this.appendText(content, 'p', 'No results in this category.');
      }
      container.appendChild(content);
      tabContents[g] = content;
    });
    container.appendChild(tabBar);
  },

  appendText(container, tagName, text, className) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = text;
    container.appendChild(element);
    return element;
  },

  renderJson(container, value, className) {
    const pre = document.createElement('pre');
    if (className) pre.className = className;
    pre.textContent = JSON.stringify(value, null, 2);
    container.replaceChildren(pre);
  },
};


App.init();
