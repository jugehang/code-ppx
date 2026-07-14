import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export class AuditReportProvider implements vscode.WebviewViewProvider {
    private view?: vscode.WebviewView;

    constructor(private extensionUri: vscode.Uri) {}

    resolveWebviewView(view: vscode.WebviewView): void | Thenable<void> {
        this.view = view;
        view.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.extensionUri],
        };
        view.webview.html = this.getEmptyHtml();
    }

    async showReport(): Promise<void> {
        // Let user pick a report
        const uris = await vscode.window.showOpenDialog({
            canSelectMany: false,
            filters: { 'Markdown': ['md'] },
            defaultUri: vscode.Uri.file(this.workspaceRoot()),
        });
        if (uris && uris.length > 0) {
            await this.loadReport(uris[0].fsPath);
        }
    }

    async loadReport(reportPath: string): Promise<void> {
        if (!fs.existsSync(reportPath)) {
            vscode.window.showErrorMessage(`Report not found: ${reportPath}`);
            return;
        }
        if (!this.view) {
            vscode.commands.executeCommand('codeppk.auditReport.focus');
        }
        const content = fs.readFileSync(reportPath, 'utf-8');
        this.renderMarkdown(content, path.basename(reportPath));
    }

    private workspaceRoot(): string {
        return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
    }

    private renderMarkdown(md: string, title: string): void {
        if (!this.view) return;
        // Simple markdown to HTML conversion
        const html = this.markdownToHtml(md);
        this.view.webview.html = `<!DOCTYPE html>
<html>
<head>
<style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px; line-height: 1.6; }
h1, h2, h3 { color: var(--vscode-textLink-foreground); }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid var(--vscode-panel-border); padding: 4px 8px; text-align: left; }
th { background: var(--vscode-editor-inactiveSelectionBackground); }
code { background: var(--vscode-textCodeBlock-background); padding: 1px 4px; border-radius: 2px; }
pre { background: var(--vscode-textCodeBlock-background); padding: 8px; border-radius: 4px; overflow-x: auto; }
strong { color: var(--vscode-textPreformat-foreground); }
</style>
</head>
<body>
${html}
</body>
</html>`;
    }

    private markdownToHtml(md: string): string {
        let html = md;
        // Headers
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
        // Bold
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Code blocks
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        // Inline code
        html = html.replace(/`(.+?)`/g, '<code>$1</code>');
        // Horizontal rule
        html = html.replace(/^---$/gm, '<hr/>');
        // Line breaks
        html = html.replace(/\n/g, '<br/>\n');
        return html;
    }

    private getEmptyHtml(): string {
        return `<!DOCTYPE html>
<html>
<head>
<style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 20px; text-align: center; }
.placeholder { color: var(--vscode-descriptionForeground); font-size: 12px; }
</style>
</head>
<body>
<div class="placeholder">
No audit report loaded.<br/>
Run an audit command or open a report file.
</div>
</body>
</html>`;
    }
}
