import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export class ConfigViewProvider implements vscode.WebviewViewProvider {
    private view?: vscode.WebviewView;

    constructor(private extensionUri: vscode.Uri) {}

    resolveWebviewView(view: vscode.WebviewView): void | Thenable<void> {
        this.view = view;
        view.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.extensionUri],
        };
        view.webview.html = this.getHtml();
        view.webview.onDidReceiveMessage((msg) => this.handleMessage(msg));
    }

    async showConfig(): Promise<void> {
        await vscode.commands.executeCommand('codeppk.config.focus');
    }

    private async handleMessage(msg: any): Promise<void> {
        const config = vscode.workspace.getConfiguration('codeppk');
        switch (msg.command) {
            case 'saveConfig':
                await config.update('llmProvider', msg.provider, vscode.ConfigurationTarget.Workspace);
                await config.update('llmModel', msg.model, vscode.ConfigurationTarget.Workspace);
                await config.update('llmBaseUrl', msg.baseUrl, vscode.ConfigurationTarget.Workspace);
                await config.update('llmApiKey', msg.apiKey, vscode.ConfigurationTarget.Workspace);
                await config.update('visionModel', msg.visionModel, vscode.ConfigurationTarget.Workspace);
                await config.update('pluginCommand', msg.pluginCmd, vscode.ConfigurationTarget.Workspace);
                await config.update('maxIterations', msg.maxIterations, vscode.ConfigurationTarget.Workspace);
                await config.update('dataFile', msg.dataFile, vscode.ConfigurationTarget.Workspace);
                await config.update('rulesFile', msg.rulesFile, vscode.ConfigurationTarget.Workspace);
                vscode.window.showInformationMessage('CodePPK configuration saved.');
                break;
            case 'testConnection':
                await this.testConnection(msg);
                break;
        }
    }

    private async testConnection(msg: any): Promise<void> {
        const python = vscode.workspace.getConfiguration('codeppk').get('pythonPath', 'python3');
        try {
            const { exec } = require('child_process');
            const cmd = `${python} -c "from openai import OpenAI; c=OpenAI(base_url='${msg.baseUrl}', api_key='${msg.apiKey}'); m=c.models.list(); print([x.id for x in m.data][:5])"`;
            exec(cmd, { cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '.' }, (err: any, stdout: string, stderr: string) => {
                if (err) {
                    this.view?.webview.postMessage({ command: 'testResult', success: false, message: stderr || err.message });
                } else {
                    this.view?.webview.postMessage({ command: 'testResult', success: true, message: stdout.trim() });
                }
            });
        } catch (e: any) {
            this.view?.webview.postMessage({ command: 'testResult', success: false, message: e.message });
        }
    }

    private getHtml(): string {
        const config = vscode.workspace.getConfiguration('codeppk');
        const provider = config.get<string>('llmProvider', 'local');
        const model = config.get<string>('llmModel', 'google/gemma-4-26b-a4b');
        const baseUrl = config.get<string>('llmBaseUrl', 'http://localhost:1234/v1');
        const apiKey = config.get<string>('llmApiKey', 'lm-studio');
        const visionModel = config.get<string>('visionModel', '');
        const pluginCmd = config.get<string>('pluginCommand', '');
        const maxIter = config.get<number>('maxIterations', 10);
        const dataFile = config.get<string>('dataFile', 'NM_dat_new.csv');
        const rulesFile = config.get<string>('rulesFile', 'poppk_rules.json');

        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 10px; }
.section { margin-bottom: 12px; }
label { display: block; font-size: 11px; color: var(--vscode-descriptionForeground); margin-bottom: 3px; text-transform: uppercase; }
input, select { width: 100%; padding: 4px 6px; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border); border-radius: 2px; }
button { padding: 6px 12px; background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; border-radius: 2px; cursor: pointer; margin-right: 4px; }
button:hover { background: var(--vscode-button-hoverBackground); }
button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
.status { margin-top: 8px; font-size: 11px; padding: 4px 6px; border-radius: 2px; display: none; }
.status.ok { background: rgba(126, 231, 135, 0.15); color: #7ee787; display: block; }
.status.err { background: rgba(255, 123, 114, 0.15); color: #ff7b72; display: block; }
.provider-group { display: flex; gap: 4px; }
.provider-group label { display: inline; margin: 0; }
.provider-group input { width: auto; margin-right: 4px; }
</style>
</head>
<body>
<div class="section">
    <label>LLM Provider</label>
    <select id="provider">
        <option value="local" ${provider==='local'?'selected':''}>Local (LM Studio / Ollama)</option>
        <option value="api" ${provider==='api'?'selected':''}>API (OpenAI / Anthropic / DeepSeek)</option>
        <option value="plugin" ${provider==='plugin'?'selected':''}>VS Code Plugin (Claude Code / Codex)</option>
    </select>
</div>
<div class="section">
    <label>Model ID</label>
    <input id="model" value="${model}" placeholder="e.g. google/gemma-4-26b-a4b or gpt-4o"/>
</div>
<div class="section">
    <label>Base URL</label>
    <input id="baseUrl" value="${baseUrl}" placeholder="http://localhost:1234/v1"/>
</div>
<div class="section">
    <label>API Key</label>
    <input id="apiKey" value="${apiKey}" type="password"/>
</div>
<div class="section">
    <label>Vision Model (for GOF/VPC audit, empty = same)</label>
    <input id="visionModel" value="${visionModel}" placeholder="e.g. gpt-4o"/>
</div>
<div class="section">
    <label>Plugin Command (for VS Code plugin provider)</label>
    <input id="pluginCmd" value="${pluginCmd}" placeholder="e.g. claude or codex"/>
</div>
<div class="section">
    <label>Max Iterations</label>
    <input id="maxIterations" type="number" value="${maxIter}" min="1" max="50"/>
</div>
<div class="section">
    <label>Data File</label>
    <input id="dataFile" value="${dataFile}"/>
</div>
<div class="section">
    <label>Rules File</label>
    <input id="rulesFile" value="${rulesFile}"/>
</div>
<div class="section">
    <button id="save">Save</button>
    <button id="test" class="secondary">Test Connection</button>
</div>
<div id="status" class="status"></div>
<script>
const vscode = acquireVsCodeApi();
document.getElementById('save').addEventListener('click', () => {
    vscode.postMessage({
        command: 'saveConfig',
        provider: document.getElementById('provider').value,
        model: document.getElementById('model').value,
        baseUrl: document.getElementById('baseUrl').value,
        apiKey: document.getElementById('apiKey').value,
        visionModel: document.getElementById('visionModel').value,
        pluginCmd: document.getElementById('pluginCmd').value,
        maxIterations: parseInt(document.getElementById('maxIterations').value),
        dataFile: document.getElementById('dataFile').value,
        rulesFile: document.getElementById('rulesFile').value,
    });
});
document.getElementById('test').addEventListener('click', () => {
    const status = document.getElementById('status');
    status.className = 'status';
    status.textContent = 'Testing...';
    status.style.display = 'block';
    vscode.postMessage({
        command: 'testConnection',
        baseUrl: document.getElementById('baseUrl').value,
        apiKey: document.getElementById('apiKey').value,
    });
});
window.addEventListener('message', (event) => {
    const msg = event.data;
    if (msg.command === 'testResult') {
        const status = document.getElementById('status');
        if (msg.success) {
            status.className = 'status ok';
            status.textContent = 'Connected: ' + msg.message;
        } else {
            status.className = 'status err';
            status.textContent = 'Failed: ' + msg.message;
        }
    }
});
</script>
</body>
</html>`;
    }
}
