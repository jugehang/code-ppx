/**
 * PopPK Agent - VS Code 扩展入口
 *
 * 提供自动化群体药动学建模的IDE集成界面
 */

const vscode = require('vscode');
const { spawn, exec } = require('child_process');
const path = require('path');
const fs = require('fs');

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    console.log('PopPK Agent 扩展已激活');

    // 注册命令: 启动自动化建模
    const startAutomation = vscode.commands.registerCommand('poppk.startAutomation', async () => {
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (!workspaceFolder) {
            vscode.window.showErrorMessage('请先打开一个工作区文件夹');
            return;
        }

        // 获取配置
        const config = vscode.workspace.getConfiguration('poppk');
        const maxIter = config.get('maxIterations', 20);
        const runVpc = config.get('runVpcEveryIteration', false);

        // 选择Python解释器
        const pythonPath = await selectPythonPath(context);

        // 创建输出通道
        const outputChannel = vscode.window.createOutputChannel('PopPK Agent');
        outputChannel.show(true);
        outputChannel.appendLine('启动 PopPK 自动化建模引擎...');
        outputChannel.appendLine(`工作目录: ${workspaceFolder}`);
        outputChannel.appendLine(`最大迭代: ${maxIter}`);
        outputChannel.appendLine(`运行VPC: ${runVpc ? '是' : '否'}`);
        outputChannel.appendLine('');

        // 运行自动化循环
        const args = [
            '-m', 'PopPK_Agent.core.automation_loop',
            '--workspace', workspaceFolder,
            '--max-iter', String(maxIter),
        ];
        if (!runVpc) args.push('--no-vpc');

        const child = spawn(pythonPath, args, {
            cwd: workspaceFolder,
            env: { ...process.env, PYTHONUNBUFFERED: '1' }
        });

        child.stdout.on('data', (data) => {
            outputChannel.append(data.toString());
        });

        child.stderr.on('data', (data) => {
            outputChannel.append(data.toString());
        });

        child.on('close', (code) => {
            if (code === 0) {
                outputChannel.appendLine('\n✅ 自动化建模完成');
                vscode.window.showInformationMessage('PopPK 自动化建模完成!');
            } else {
                outputChannel.appendLine(`\n❌ 进程退出码: ${code}`);
                vscode.window.showErrorMessage('PopPK 自动化建模失败');
            }
        });
    });

    // 注册命令: 运行单个模型
    const runModel = vscode.commands.registerCommand('poppk.runModel', async () => {
        const runId = await vscode.window.showInputBox({
            prompt: '输入要运行的模型编号 (如 41)',
            validateInput: (value) => value.match(/^\d+$/) ? null : '请输入数字'
        });
        if (!runId) return;

        const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const modFile = path.join(workspaceFolder, `run${runId}.mod`);
        if (!fs.existsSync(modFile)) {
            vscode.window.showErrorMessage(`模型文件不存在: run${runId}.mod`);
            return;
        }

        vscode.window.showInformationMessage(`运行 NONMEM Run ${runId}...`);
        // TODO: 调用NONMEM运行
    });

    // 注册命令: GOF图AI审计
    const auditGOF = vscode.commands.registerCommand('poppk.auditGOF', async () => {
        const runId = await vscode.window.showInputBox({
            prompt: '输入模型编号进行GOF审计',
            validateInput: (value) => value.match(/^\d+$/) ? null : '请输入数字'
        });
        if (!runId) return;

        const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const gofImage = path.join(workspaceFolder, `GOF_mod${runId}.jpg`);

        if (!fs.existsSync(gofImage)) {
            vscode.window.showErrorMessage(`GOF图不存在: GOF_mod${runId}.jpg`);
            return;
        }

        // 在Webview中显示GOF图
        const panel = vscode.window.createWebviewPanel(
            'gofAudit',
            `GOF审计 - Run ${runId}`,
            vscode.ViewColumn.Two,
            { enableScripts: true }
        );

        const imageBuffer = fs.readFileSync(gofImage).toString('base64');
        panel.webview.html = getGOFWebviewContent(imageBuffer, runId);
    });

    // 注册命令: 配置LLM
    const configureLLM = vscode.commands.registerCommand('poppk.configureLLM', async () => {
        const config = vscode.workspace.getConfiguration('poppk');
        const backends = ['lmstudio', 'ollama', 'openai', 'claude', 'claude_code', 'codex'];
        const selected = await vscode.window.showQuickPick(backends, {
            placeHolder: `当前: ${config.get('llmBackend')}`
        });
        if (selected) {
            await config.update('llmBackend', selected, vscode.ConfigurationTarget.Workspace);
            vscode.window.showInformationMessage(`LLM后端已切换为: ${selected}`);
        }
    });

    // 注册命令: 查看规则库
    const viewRules = vscode.commands.registerCommand('poppk.viewRules', async () => {
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const rulesFile = path.join(workspaceFolder, 'PopPK_Agent', 'poppk_rules.json');
        if (!fs.existsSync(rulesFile)) {
            vscode.window.showErrorMessage('规则库文件不存在');
            return;
        }
        const doc = await vscode.workspace.openTextDocument(rulesFile);
        await vscode.window.showTextDocument(doc);
    });

    // 注册TreeDataProvider
    const treeProvider = new PopPKTreeProvider();
    vscode.window.registerTreeDataProvider('poppkExplorer', treeProvider);

    context.subscriptions.push(
        startAutomation, runModel, auditGOF, configureLLM, viewRules
    );

    vscode.commands.executeCommand('setContext', 'poppk.activated', true);
}

function getGOFWebviewContent(imageBase64, runId) {
    return `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>GOF审计 - Run ${runId}</title>
    <style>
        body { font-family: sans-serif; margin: 0; padding: 20px; background: #1e1e1e; color: #d4d4d4; }
        .header { font-size: 20px; font-weight: bold; margin-bottom: 16px; }
        .image-container { text-align: center; }
        .image-container img { max-width: 100%; border: 1px solid #444; }
        .controls { margin: 16px 0; }
        button { background: #0e639c; color: white; border: none; padding: 8px 16px; cursor: pointer; }
        button:hover { background: #1177bb; }
    </style>
</head>
<body>
    <div class="header">GOF诊断图审计 - Run ${runId}</div>
    <div class="controls">
        <button onclick="runAudit()">AI审计</button>
    </div>
    <div class="image-container">
        <img src="data:image/jpeg;base64,${imageBase64}" />
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        function runAudit() {
            vscode.postMessage({ command: 'audit', runId: ${runId} });
        }
    </script>
</body>
</html>`;
}

class PopPKTreeProvider {
    constructor() {
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    }

    refresh() {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element) {
        return element;
    }

    getChildren(element) {
        if (!element) {
            return [
                new vscode.TreeItem('模型列表', vscode.TreeItemCollapsibleState.Expanded),
                new vscode.TreeItem('诊断报告', vscode.TreeItemCollapsibleState.Collapsed),
                new vscode.TreeItem('规则库', vscode.TreeItemCollapsibleState.None),
            ];
        }
        return [];
    }
}

async function selectPythonPath(context) {
    const config = vscode.workspace.getConfiguration('poppk');
    // 尝试从Python扩展获取解释器
    const pythonExtension = vscode.extensions.getExtension('ms-python.python');
    if (pythonExtension) {
        const pythonApi = await pythonExtension.activate();
        const activeInterpreter = pythonApi.settings.getExecutionDetails()?.execCommand;
        if (activeInterpreter) {
            return activeInterpreter[0];
        }
    }
    return 'python3';
}

function deactivate() {
    console.log('PopPK Agent 扩展已停用');
}

module.exports = {
    activate,
    deactivate
};
