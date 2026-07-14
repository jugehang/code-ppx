import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

type AssetCategory = 'models' | 'data' | 'outputs' | 'figures' | 'reports' | 'scripts';

export class CodePPKProvider implements vscode.TreeDataProvider<AssetItem> {
    private _onDidChange = new vscode.EventEmitter<void>();
    readonly onDidChangeTreeData = this._onDidChange.event;

    constructor(private workspaceRoot: string) {}

    refresh(): void {
        this._onDidChange.fire();
    }

    getTreeItem(element: AssetItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: AssetItem): Thenable<AssetItem[]> {
        if (!this.workspaceRoot) {
            return Promise.resolve([new AssetItem('Open a workspace folder', '', 'info', vscode.TreeItemCollapsibleState.None)]);
        }

        if (!element) {
            return Promise.resolve(this.getCategories());
        }

        if (element.itemType === 'category') {
            return Promise.resolve(this.getAssets(element.assetType!));
        }

        return Promise.resolve([]);
    }

    private getCategories(): AssetItem[] {
        const cats: { label: string; type: AssetCategory; icon: string }[] = [
            { label: 'Models (.mod)', type: 'models', icon: 'symbol-class' },
            { label: 'Data Files', type: 'data', icon: 'database' },
            { label: 'NONMEM Outputs (.lst)', type: 'outputs', icon: 'output' },
            { label: 'Figures (GOF/VPC)', type: 'figures', icon: 'image' },
            { label: 'Audit Reports', type: 'reports', icon: 'book' },
            { label: 'Scripts (R/Python)', type: 'scripts', icon: 'file-code' },
        ];
        return cats.map(c => new AssetItem(c.label, '', 'category', vscode.TreeItemCollapsibleState.Collapsed, c.icon, c.type));
    }

    private getAssets(category: AssetCategory): AssetItem[] {
        const root = this.workspaceRoot;
        if (!fs.existsSync(root)) return [];

        const files = fs.readdirSync(root);
        const items: AssetItem[] = [];

        for (const file of files) {
            const filePath = path.join(root, file);
            if (!fs.statSync(filePath).isFile()) continue;
            const ext = path.extname(file).toLowerCase();
            let match = false;

            switch (category) {
                case 'models':
                    match = /^run\d+\.mod$/i.test(file);
                    break;
                case 'data':
                    match = ext === '.csv' || /^(SDTAB|PATAB|CATAB|COTAB)/i.test(file);
                    break;
                case 'outputs':
                    match = /^run\d+\.(lst|ext|cov)$/i.test(file);
                    break;
                case 'figures':
                    match = ['.jpg', '.jpeg', '.png', '.pdf'].includes(ext) &&
                            /^(GOF_mod|VPC_mod|VPC_Stratified)/i.test(file);
                    break;
                case 'reports':
                    match = ext === '.md' || ext === '.docx';
                    break;
                case 'scripts':
                    match = ext === '.r' || ext === '.py';
                    break;
            }

            if (match) {
                const item = new AssetItem(
                    file,
                    filePath,
                    'file',
                    vscode.TreeItemCollapsibleState.None,
                    this.getIconForFile(ext),
                    category
                );
                item.command = {
                    command: 'vscode.open',
                    title: 'Open',
                    arguments: [vscode.Uri.file(filePath)],
                };
                items.push(item);
            }
        }

        // Also check Compare* directories for reports
        if (category === 'reports' || category === 'figures') {
            for (const dir of files) {
                const dirPath = path.join(root, dir);
                if (dir.startsWith('Compare') && fs.statSync(dirPath).isDirectory()) {
                    for (const subFile of fs.readdirSync(dirPath)) {
                        const subPath = path.join(dirPath, subFile);
                        const subExt = path.extname(subFile).toLowerCase();
                        if (category === 'reports' && ['.md', '.docx', '.xlsx'].includes(subExt)) {
                            const item = new AssetItem(
                                `${dir}/${subFile}`,
                                subPath,
                                'file',
                                vscode.TreeItemCollapsibleState.None,
                                this.getIconForFile(subExt),
                                category
                            );
                            item.command = {
                                command: 'vscode.open',
                                title: 'Open',
                                arguments: [vscode.Uri.file(subPath)],
                            };
                            items.push(item);
                        }
                        if (category === 'figures' && ['.jpg', '.jpeg', '.png', '.pdf'].includes(subExt)) {
                            const item = new AssetItem(
                                `${dir}/${subFile}`,
                                subPath,
                                'file',
                                vscode.TreeItemCollapsibleState.None,
                                'image',
                                category
                            );
                            item.command = {
                                command: 'vscode.open',
                                title: 'Open',
                                arguments: [vscode.Uri.file(subPath)],
                            };
                            items.push(item);
                        }
                    }
                }
            }
        }

        return items.sort((a, b) => a.label!.localeCompare(b.label!));
    }

    private getIconForFile(ext: string): string {
        switch (ext) {
            case '.mod': return 'symbol-class';
            case '.lst': return 'output';
            case '.csv': return 'database';
            case '.jpg':
            case '.jpeg':
            case '.png': return 'image';
            case '.pdf': return 'file-pdf';
            case '.md': return 'book';
            case '.r': return 'file-code';
            case '.py': return 'file-code';
            default: return 'file';
        }
    }
}

export class AssetItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly filePath: string,
        public readonly itemType: 'category' | 'file' | 'info',
        collapsibleState: vscode.TreeItemCollapsibleState,
        icon?: string,
        public readonly assetType?: AssetCategory,
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;
        if (icon) {
            this.iconPath = new vscode.ThemeIcon(icon);
        }
    }
}
