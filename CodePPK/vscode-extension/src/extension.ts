import * as vscode from 'vscode';
import { CodePPKProvider } from './treeProvider';
import { CodePPKRunner } from './runner';
import { ConfigViewProvider } from './configView';
import { AuditReportProvider } from './auditReport';

export function activate(context: vscode.ExtensionContext) {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
    const outputChannel = vscode.window.createOutputChannel('CodePPK');
    outputChannel.show(true);
    outputChannel.appendLine('CodePPK extension activated');
    outputChannel.appendLine(`Workspace: ${workspaceRoot}`);

    // Tree data provider for explorer
    const treeProvider = new CodePPKProvider(workspaceRoot);
    vscode.window.registerTreeDataProvider('codeppk.explorer', treeProvider);

    // Tree data provider for modeling loop
    const loopProvider = new CodePPKProvider(workspaceRoot);
    vscode.window.registerTreeDataProvider('codeppk.runs', loopProvider);

    // Config webview provider
    const configProvider = new ConfigViewProvider(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('codeppk.config', configProvider)
    );

    // Audit report webview serializer
    const auditProvider = new AuditReportProvider(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('codeppk.auditReport', auditProvider)
    );

    // Create the runner
    const runner = new CodePPKRunner(workspaceRoot, outputChannel, treeProvider, loopProvider);

    // Register commands
    const commands: [string, () => void][] = [
        ['codeppk.run', () => runner.runModelingLoop()],
        ['codeppk.stopLoop', () => runner.stopLoop()],
        ['codeppk.runNonmem', () => runner.runNonmem()],
        ['codeppk.runGOF', () => runner.runGOF()],
        ['codeppk.runVPC', () => runner.runVPC()],
        ['codeppk.auditLST', () => runner.auditLST()],
        ['codeppk.auditGOF', () => runner.auditGOF()],
        ['codeppk.auditVPC', () => runner.auditVPC()],
        ['codeppk.analyzeData', () => runner.analyzeData()],
        ['codeppk.generateModel', () => runner.generateModel()],
        ['codeppk.validateModel', () => runner.validateModel()],
        ['codeppk.openGOFImage', () => runner.openImage('GOF')],
        ['codeppk.openVPCImage', () => runner.openImage('VPC')],
        ['codeppk.refreshExplorer', () => treeProvider.refresh()],
        ['codeppk.configureLLM', () => configProvider.showConfig()],
        ['codeppk.openAuditReport', () => auditProvider.showReport()],
    ];

    commands.forEach(([cmd, fn]) => {
        context.subscriptions.push(vscode.commands.registerCommand(cmd, fn));
    });

    // Watch for file changes to refresh tree
    const watcher = vscode.workspace.createFileSystemWatcher(
        '**/{run*.lst,run*.mod,GOF_mod*,VPC_mod*,*.md}',
        false, false, false
    );
    watcher.onDidChange(() => treeProvider.refresh());
    watcher.onDidCreate(() => treeProvider.refresh());
    context.subscriptions.push(watcher);

    // Status bar
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    statusBar.text = '$(beaker) CodePPK Ready';
    statusBar.tooltip = 'CodePPK Automated PopPK Modeling';
    statusBar.command = 'codeppk.run';
    statusBar.show();
    context.subscriptions.push(statusBar);

    runner.onStatusChange((status: string) => {
        statusBar.text = `$(beaker) ${status}`;
    });

    outputChannel.appendLine('CodePPK commands registered. Ready to use.');
}

export function deactivate() {
    console.log('CodePPK extension deactivated');
}
