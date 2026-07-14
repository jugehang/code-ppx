import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { execSync, spawn, ChildProcess } from 'child_process';
import { CodePPKProvider } from './treeProvider';

export class CodePPKRunner {
    private currentLoopProcess: ChildProcess | null = null;
    private _onStatusChange = new vscode.EventEmitter<string>();
    readonly onStatusChange = this._onStatusChange.event;

    constructor(
        private workspaceRoot: string,
        private outputChannel: vscode.OutputChannel,
        private treeProvider: CodePPKProvider,
        private loopProvider: CodePPKProvider,
    ) {}

    private getConfig(): vscode.WorkspaceConfiguration {
        return vscode.workspace.getConfiguration('codeppk');
    }

    private getPythonCmd(): string {
        return this.getConfig().get('pythonPath', 'python3');
    }

    private getCodeppkModule(): string {
        // Find the codeppk package relative to this extension
        const extPath = vscode.extensions.getExtension('codeppk')?.extensionPath || '';
        if (extPath) {
            return path.join(extPath, '..', 'codeppk');
        }
        // Fallback: assume it's installed
        return 'codeppk';
    }

    private log(msg: string): void {
        this.outputChannel.appendLine(`[${new Date().toLocaleTimeString()}] ${msg}`);
    }

    private async runCodeppk(args: string[]): Promise<number> {
        const python = this.getPythonCmd();
        const module = 'codeppk.cli';
        const fullArgs = ['-m', module, ...args];
        this.log(`$ ${python} ${fullArgs.join(' ')}`);

        return new Promise((resolve) => {
            const proc = spawn(python, fullArgs, {
                cwd: this.workspaceRoot,
                stdio: ['ignore', 'pipe', 'pipe'],
            });

            proc.stdout.on('data', (data) => {
                this.outputChannel.append(data.toString());
            });
            proc.stderr.on('data', (data) => {
                this.outputChannel.append(data.toString());
            });
            proc.on('close', (code) => {
                this.log(`[exit ${code}]`);
                this.treeProvider.refresh();
                resolve(code || 0);
            });
        });
    }

    private getLLMArgs(): string[] {
        const config = this.getConfig();
        const args: string[] = [];
        args.push('--llm-provider', config.get('llmProvider', 'local'));
        args.push('--llm-model', config.get('llmModel', 'google/gemma-4-26b-a4b'));
        args.push('--llm-url', config.get('llmBaseUrl', 'http://localhost:1234/v1'));
        args.push('--api-key', config.get('llmApiKey', 'lm-studio'));
        const pluginCmd = config.get('pluginCommand', '');
        if (pluginCmd) {
            args.push('--plugin-cmd', pluginCmd);
        }
        return args;
    }

    async runModelingLoop(): Promise<void> {
        if (this.currentLoopProcess) {
            vscode.window.showWarningMessage('Modeling loop is already running.');
            return;
        }

        const config = this.getConfig();
        const maxIter = config.get('maxIterations', 10);
        const dataFile = config.get('dataFile', 'NM_dat_new.csv');
        const rulesFile = config.get('rulesFile', 'poppk_rules.json');

        const runId = await vscode.window.showInputBox({
            prompt: 'Starting run number',
            value: '1',
            validateInput: (v) => /^\d+$/.test(v) ? null : 'Must be a number',
        });
        if (!runId) return;

        this._onStatusChange.fire('Running modeling loop...');
        this.log('=== Starting automated PopPK modeling loop ===');

        const args = [
            'run',
            '--project', this.workspaceRoot,
            '--data', dataFile,
            '--rules', rulesFile,
            '--start-run', runId,
            '--max-iterations', String(maxIter),
            ...this.getLLMArgs(),
        ];

        const python = this.getPythonCmd();
        const fullArgs = ['-m', 'codeppk.cli', ...args];
        this.log(`$ ${python} ${fullArgs.join(' ')}`);

        this.currentLoopProcess = spawn(python, fullArgs, {
            cwd: this.workspaceRoot,
            stdio: ['ignore', 'pipe', 'pipe'],
        });

        this.currentLoopProcess.stdout?.on('data', (data) => {
            this.outputChannel.append(data.toString());
        });
        this.currentLoopProcess.stderr?.on('data', (data) => {
            this.outputChannel.append(data.toString());
        });
        this.currentLoopProcess.on('close', (code) => {
            this.log(`=== Modeling loop finished (exit ${code}) ===`);
            this._onStatusChange.fire('Ready');
            this.currentLoopProcess = null;
            vscode.commands.executeCommand('setContext', 'codeppk.loopRunning', false);
            this.treeProvider.refresh();
            this.loopProvider.refresh();
            if (code === 0) {
                vscode.window.showInformationMessage('CodePPK modeling loop completed successfully!');
            } else {
                vscode.window.showWarningMessage(`Modeling loop exited with code ${code}`);
            }
        });

        vscode.commands.executeCommand('setContext', 'codeppk.loopRunning', true);
    }

    stopLoop(): void {
        if (this.currentLoopProcess) {
            this.currentLoopProcess.kill('SIGTERM');
            this.log('Modeling loop stopped by user.');
            this._onStatusChange.fire('Stopped');
            this.currentLoopProcess = null;
            vscode.commands.executeCommand('setContext', 'codeppk.loopRunning', false);
        }
    }

    async runNonmem(): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;
        this._onStatusChange.fire(`Running NONMEM (Run ${runId})...`);
        await this.runCodeppk(['audit', '--curr', runId, '--type', 'lst', '--project', this.workspaceRoot, ...this.getLLMArgs()]);
        this._onStatusChange.fire('Ready');
    }

    async runGOF(): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;
        this._onStatusChange.fire('Generating GOF plots...');
        await this.runCodeppk(['audit', '--curr', runId, '--type', 'gof', '--project', this.workspaceRoot, ...this.getLLMArgs()]);
        this._onStatusChange.fire('Ready');
    }

    async runVPC(): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;
        this._onStatusChange.fire('Generating VPC plots...');
        await this.runCodeppk(['audit', '--curr', runId, '--type', 'vpc', '--project', this.workspaceRoot, ...this.getLLMArgs()]);
        this._onStatusChange.fire('Ready');
    }

    async auditLST(): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;
        const prevId = await vscode.window.showInputBox({
            prompt: 'Previous run ID (for comparison, optional)',
            value: '',
        });
        this._onStatusChange.fire('Auditing LST parameters...');
        const args = ['audit', '--curr', runId, '--type', 'all', '--project', this.workspaceRoot, ...this.getLLMArgs()];
        if (prevId) args.push('--prev', prevId);
        await this.runCodeppk(args);
        this._onStatusChange.fire('Ready');
    }

    async auditGOF(): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;
        this._onStatusChange.fire('AI auditing GOF plot...');
        await this.runCodeppk(['audit', '--curr', runId, '--type', 'gof', '--project', this.workspaceRoot, ...this.getLLMArgs()]);
        this._onStatusChange.fire('Ready');
        // Open the generated report if exists
        this.openReport(`GOF_AI_Audit_Run${runId}.md`);
    }

    async auditVPC(): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;
        this._onStatusChange.fire('AI auditing VPC plot...');
        await this.runCodeppk(['audit', '--curr', runId, '--type', 'vpc', '--project', this.workspaceRoot, ...this.getLLMArgs()]);
        this._onStatusChange.fire('Ready');
        this.openReport(`VPC_AI_Audit_Run${runId}.md`);
    }

    async analyzeData(): Promise<void> {
        const dataFile = this.getConfig().get('dataFile', 'NM_dat_new.csv');
        const dataPath = path.join(this.workspaceRoot, dataFile);
        if (!fs.existsSync(dataPath)) {
            vscode.window.showErrorMessage(`Data file not found: ${dataPath}`);
            return;
        }
        this._onStatusChange.fire('Analyzing dataset...');
        await this.runCodeppk(['features', '--data', dataPath]);
        this._onStatusChange.fire('Ready');
    }

    async generateModel(): Promise<void> {
        const templateItems = [
            'iv_infusion_1c_advan1_trans2',
            'iv_bolus_1c_advan1_trans2',
            'iv_infusion_2c_advan3_trans4',
            'iv_bolus_2c_advan3_trans4',
            'extravascular_1c_advan2_trans2',
            'extravascular_2c_advan4_trans4',
        ];
        const template = await vscode.window.showQuickPick(templateItems, {
            placeHolder: 'Select a NONMEM model template',
        });
        if (!template) return;

        const runId = await vscode.window.showInputBox({
            prompt: 'Run number',
            value: '1',
            validateInput: (v) => /^\d+$/.test(v) ? null : 'Must be a number',
        });
        if (!runId) return;

        const dataFile = this.getConfig().get('dataFile', 'NM_dat_new.csv');
        const outputPath = path.join(this.workspaceRoot, `run${runId}.mod`);

        this._onStatusChange.fire('Generating model...');
        await this.runCodeppk([
            'generate',
            '--template', template,
            '--run', runId,
            '--data', dataFile,
            '--output', outputPath,
        ]);
        this._onStatusChange.fire('Ready');

        // Open the generated file
        const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(outputPath));
        await vscode.window.showTextDocument(doc);
    }

    async validateModel(): Promise<void> {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.mod')) {
            vscode.window.showErrorMessage('Please open a .mod file first.');
            return;
        }
        const modPath = editor.document.fileName;
        const dataFile = this.getConfig().get('dataFile', 'NM_dat_new.csv');
        const csvPath = path.join(this.workspaceRoot, dataFile);

        this._onStatusChange.fire('Validating model...');
        await this.runCodeppk([
            'validate',
            '--mod', modPath,
            '--project-dir', path.dirname(modPath),
            '--csv', csvPath,
        ]);
        this._onStatusChange.fire('Ready');
    }

    async openImage(prefix: string): Promise<void> {
        const runId = await this.askRunId();
        if (!runId) return;

        const extensions = ['jpg', 'JPG', 'jpeg', 'JPEG', 'png', 'PNG'];
        for (const ext of extensions) {
            const imgPath = path.join(this.workspaceRoot, `${prefix}_mod${runId}.${ext}`);
            if (fs.existsSync(imgPath)) {
                await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(imgPath));
                return;
            }
        }
        vscode.window.showWarningMessage(`No ${prefix} image found for run ${runId}.`);
    }

    private async openReport(filename: string): Promise<void> {
        const reportPath = path.join(this.workspaceRoot, filename);
        if (fs.existsSync(reportPath)) {
            await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(reportPath));
        }
    }

    private async askRunId(): Promise<string | undefined> {
        return vscode.window.showInputBox({
            prompt: 'Run ID',
            value: '41',
            validateInput: (v) => /^\d+$/.test(v) ? null : 'Must be a number',
        });
    }
}
