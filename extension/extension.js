const vscode = require('vscode');
const path = require('path');
const fs = require('fs');

/** @type {vscode.StatusBarItem} */
let statusBarItem;
/** @type {vscode.FileSystemWatcher} */
let watcher;
/** @type {vscode.FileSystemWatcher} */
let codexWatcher;
/** @type {vscode.FileSystemWatcher} */
let bridgeDirWatcher;
/** @type {vscode.FileSystemWatcher} */
let responseWatcher;
/** @type {boolean} */
let processingGemini = false;
/** @type {boolean} */
let processingCodex = false;
/** @type {NodeJS.Timeout|null} */
let autoApproveTimer = null;
/** @type {NodeJS.Timeout|null} */
let responseTimer = null;
/** @type {number} */
let retryCount = 0;
/** @type {Set<string>} */
let knownResponseFiles = new Set();
/** @type {string|null} - 현재 응답 대기 중인 타겟 */
let activeTarget = null;

/** 자동 승인 폴링 지속 시간 (ms) — RESPONSE_TIMEOUT * MAX_RETRIES 보다 길어야 함 */
const AUTO_APPROVE_DURATION = 2100000;
/** 자동 승인 폴링 간격 (ms) */
const AUTO_APPROVE_INTERVAL = 2000;
/** 응답 대기 타임아웃 (ms) — 이 시간 내에 응답 없으면 continue 전송 */
const RESPONSE_TIMEOUT = 600000;
/** 최대 continue 재시도 횟수 */
const MAX_RETRIES = 3;

// =======================================================================
//  디렉토리 탐색
// =======================================================================

function findBridgeDir() {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) return null;
    for (const folder of folders) {
        const candidate = path.join(folder.uri.fsPath, 'bridge', 'from-claude');
        if (fs.existsSync(candidate)) return candidate;
    }
    return null;
}

function findResponseDir(target) {
    const sub = target === 'codex' ? 'from-codex' : 'from-gemini';
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) return null;
    for (const folder of folders) {
        const candidate = path.join(folder.uri.fsPath, 'bridge', sub);
        if (fs.existsSync(candidate)) return candidate;
    }
    return null;
}

function snapshotResponseFiles(target) {
    const responseDir = findResponseDir(target);
    knownResponseFiles.clear();
    if (responseDir && fs.existsSync(responseDir)) {
        for (const f of fs.readdirSync(responseDir)) {
            if (f.endsWith('.md')) knownResponseFiles.add(f);
        }
    }
}

// =======================================================================
//  Gemini 트리거 처리
// =======================================================================

async function handleGeminiTrigger(uri) {
    if (processingGemini) return;
    processingGemini = true;

    try {
        const filePath = uri.fsPath;
        if (!filePath.endsWith('.trigger')) return;

        const content = fs.readFileSync(filePath, 'utf-8').trim();
        if (!content) {
            vscode.window.showWarningMessage('Claude Bridge: 빈 트리거 파일 무시됨');
            return;
        }

        snapshotResponseFiles('gemini');
        retryCount = 0;
        activeTarget = 'gemini';

        updateStatus('$(sync~spin) Gemini 전송...');

        try {
            await vscode.commands.executeCommand('antigravity.sendPromptToAgentPanel', content);
        } catch (e) {
            await vscode.commands.executeCommand('antigravity.sendTextToChat', content);
        }

        try { fs.unlinkSync(filePath); } catch (e) { /* ignore */ }

        startAutoApprove();
        startResponseWatch('gemini');

        updateStatus('$(sync~spin) Gemini 응답 대기...');
        vscode.window.showInformationMessage(
            `Claude Bridge: Gemini 전송 완료 (${content.length}자)`
        );
    } catch (err) {
        vscode.window.showErrorMessage(`Claude Bridge 오류: ${err.message}`);
        updateStatus('$(error) Error');
        setTimeout(() => updateStatus('$(plug) Claude Bridge'), 3000);
    } finally {
        processingGemini = false;
    }
}

// =======================================================================
//  Codex 트리거 처리
// =======================================================================

async function handleCodexTrigger(uri) {
    if (processingCodex) return;
    processingCodex = true;

    try {
        const filePath = uri.fsPath;
        if (!filePath.endsWith('.codex-trigger')) return;

        const raw = fs.readFileSync(filePath, 'utf-8').trim();
        if (!raw) {
            vscode.window.showWarningMessage('Claude Bridge: 빈 Codex 트리거 무시됨');
            return;
        }

        // frontmatter 이후의 본문만 추출
        let content = raw;
        const fmMatch = raw.match(/^---[\s\S]*?---\s*([\s\S]*)$/);
        if (fmMatch) content = fmMatch[1].trim();

        // frontmatter에서 response_file 추출
        let responseFile = null;
        const rfMatch = raw.match(/^response_file:\s*"?([^"\n]+)"?/m);
        if (rfMatch) responseFile = rfMatch[1].trim();

        snapshotResponseFiles('codex');
        activeTarget = 'codex';

        updateStatus('$(sync~spin) Codex 전송...');

        // implementTodo로 Codex에 전송
        // fileName에 응답 파일 경로를 넣으면 Codex가 해당 파일에 작업함
        const targetFile = responseFile || 'bridge/from-codex/response.md';
        await vscode.commands.executeCommand('chatgpt.implementTodo', {
            line: 1,
            fileName: targetFile,
            comment: content,
        });

        try { fs.unlinkSync(filePath); } catch (e) { /* ignore */ }

        startResponseWatch('codex');

        updateStatus('$(sync~spin) Codex 응답 대기...');
        vscode.window.showInformationMessage(
            `Claude Bridge: Codex 전송 완료 (${content.length}자)`
        );
    } catch (err) {
        vscode.window.showErrorMessage(`Claude Bridge Codex 오류: ${err.message}`);
        updateStatus('$(error) Error');
        setTimeout(() => updateStatus('$(plug) Claude Bridge'), 3000);
    } finally {
        processingCodex = false;
    }
}

// =======================================================================
//  응답 대기 + 자동 continue
// =======================================================================

function startResponseWatch(target) {
    stopResponseWatch();

    const responseDir = findResponseDir(target);
    if (responseDir) {
        const pattern = new vscode.RelativePattern(responseDir, '*.md');
        responseWatcher = vscode.workspace.createFileSystemWatcher(pattern);
        responseWatcher.onDidCreate((uri) => {
            const filename = path.basename(uri.fsPath);
            if (!knownResponseFiles.has(filename)) {
                onResponseReceived(target, filename);
            }
        });
    }

    // Gemini만 auto-continue (Codex는 에이전트가 알아서 함)
    if (target === 'gemini') {
        scheduleRetry();
    }
}

function scheduleRetry() {
    if (responseTimer) clearTimeout(responseTimer);

    responseTimer = setTimeout(async () => {
        retryCount++;

        if (retryCount > MAX_RETRIES) {
            updateStatus('$(error) 응답 없음');
            vscode.window.showWarningMessage(
                `Claude Bridge: ${MAX_RETRIES}회 재시도 후에도 응답 없음. 수동 확인 필요.`
            );
            stopResponseWatch();
            stopAutoApprove();
            setTimeout(() => updateStatus('$(plug) Claude Bridge'), 5000);
            return;
        }

        updateStatus(`$(sync~spin) continue 전송 (${retryCount}/${MAX_RETRIES})...`);
        console.log(`Claude Bridge: 응답 타임아웃, continue 전송 (${retryCount}/${MAX_RETRIES})`);

        try {
            await vscode.commands.executeCommand('antigravity.sendPromptToAgentPanel', 'continue');
        } catch (e) {
            try {
                await vscode.commands.executeCommand('antigravity.sendTextToChat', 'continue');
            } catch (e2) { /* ignore */ }
        }

        scheduleRetry();
    }, RESPONSE_TIMEOUT);
}

function onResponseReceived(target, filename) {
    const label = target === 'codex' ? 'Codex' : 'Gemini';
    console.log(`Claude Bridge: ${label} 응답 감지 → ${filename}`);
    updateStatus(`$(check) ${label} 응답 완료`);
    vscode.window.showInformationMessage(
        `Claude Bridge: ${label} 응답 완료 → ${filename}`
    );

    stopResponseWatch();
    stopAutoApprove();
    activeTarget = null;

    setTimeout(() => updateStatus('$(plug) Claude Bridge'), 3000);
}

function stopResponseWatch() {
    if (responseTimer) { clearTimeout(responseTimer); responseTimer = null; }
    if (responseWatcher) { responseWatcher.dispose(); responseWatcher = null; }
}

// =======================================================================
//  수동 명령어
// =======================================================================

async function sendMessageCommand() {
    const target = await vscode.window.showQuickPick(['Gemini', 'Codex'], {
        placeHolder: '전송 대상을 선택하세요',
    });
    if (!target) return;

    const message = await vscode.window.showInputBox({
        prompt: `${target}에 보낼 메시지를 입력하세요`,
        placeHolder: '메시지 입력...',
    });
    if (!message) return;

    const bridgeDir = findBridgeDir();
    if (!bridgeDir) {
        vscode.window.showErrorMessage(
            'Claude Bridge: bridge/from-claude/ 디렉토리를 찾을 수 없습니다.'
        );
        return;
    }

    const ext = target === 'Codex' ? '.codex-trigger' : '.trigger';
    const triggerPath = path.join(bridgeDir, `manual-${Date.now()}${ext}`);
    fs.writeFileSync(triggerPath, message, 'utf-8');
}

async function listCommandsCommand() {
    const allCommands = await vscode.commands.getCommands(true);
    const keywords = ['antigravity', 'cascade', 'chat', 'agent', 'send', 'submit', 'paste', 'mention', 'chatgpt', 'codex'];
    const matches = allCommands.filter(cmd => {
        const lower = cmd.toLowerCase();
        return keywords.some(kw => lower.includes(kw));
    });
    matches.sort();

    const bridgeDir = findBridgeDir();
    const outPath = bridgeDir
        ? path.join(path.dirname(bridgeDir), 'available-commands.txt')
        : '/tmp/antigravity-commands.txt';

    fs.writeFileSync(outPath, matches.join('\n'), 'utf-8');
    vscode.window.showInformationMessage(
        `Claude Bridge: ${matches.length}개 명령어 발견 → ${outPath}`
    );
}

// =======================================================================
//  상태바 + 유틸
// =======================================================================

function updateStatus(text) {
    if (statusBarItem) statusBarItem.text = text;
}

// =======================================================================
//  자동 승인 (Gemini용)
// =======================================================================

function startAutoApprove() {
    stopAutoApprove();
    let elapsed = 0;

    const approveCommands = [
        'antigravity.agent.acceptAgentStep',
        'antigravity.command.accept',
        'antigravity.terminalCommand.accept',
    ];

    autoApproveTimer = setInterval(async () => {
        elapsed += AUTO_APPROVE_INTERVAL;
        for (const cmd of approveCommands) {
            try { await vscode.commands.executeCommand(cmd); } catch (e) { /* ignore */ }
        }
        if (elapsed >= AUTO_APPROVE_DURATION) stopAutoApprove();
    }, AUTO_APPROVE_INTERVAL);
}

function stopAutoApprove() {
    if (autoApproveTimer) { clearInterval(autoApproveTimer); autoApproveTimer = null; }
}

// =======================================================================
//  활성화 / 비활성화
// =======================================================================

function activate(context) {
    console.log('Claude Bridge 익스텐션 활성화됨 (Gemini + Codex)');

    // 상태바
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusBarItem.command = 'claudeBridge.showStatus';
    updateStatus('$(plug) Claude Bridge');
    statusBarItem.tooltip = 'Claude Bridge — Gemini + Codex 브릿지';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // 명령어 등록
    context.subscriptions.push(
        vscode.commands.registerCommand('claudeBridge.sendMessage', sendMessageCommand)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('claudeBridge.showStatus', () => {
            const bridgeDir = findBridgeDir();
            const geminiDir = findResponseDir('gemini');
            const codexDir = findResponseDir('codex');
            const parts = [];
            if (bridgeDir) parts.push(`트리거: ${bridgeDir}`);
            if (geminiDir) parts.push('Gemini ✅');
            if (codexDir) parts.push('Codex ✅');
            if (parts.length > 0) {
                vscode.window.showInformationMessage(`Claude Bridge | ${parts.join(' | ')}`);
            } else {
                vscode.window.showWarningMessage('Claude Bridge: bridge/ 디렉토리를 찾을 수 없습니다.');
            }
        })
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('claudeBridge.listCommands', listCommandsCommand)
    );

    // watcher 설정
    setupWatchers(context);

    context.subscriptions.push(
        vscode.workspace.onDidChangeWorkspaceFolders(() => {
            disposeWatchers();
            setupWatchers(context);
        })
    );
}

function setupWatchers(context) {
    const bridgeDir = findBridgeDir();
    if (!bridgeDir) {
        console.log('Claude Bridge: bridge/from-claude/ 미발견, 디렉토리 생성 감시...');
        updateStatus('$(plug) Claude Bridge (대기)');
        startBridgeDirWatcher(context);
        return;
    }

    stopBridgeDirWatcher();

    // Gemini 트리거 (.trigger) 감시
    const geminiPattern = new vscode.RelativePattern(bridgeDir, '*.trigger');
    watcher = vscode.workspace.createFileSystemWatcher(geminiPattern);
    watcher.onDidCreate(handleGeminiTrigger);
    watcher.onDidChange(handleGeminiTrigger);
    context.subscriptions.push(watcher);

    // Codex 트리거 (.codex-trigger) 감시
    const codexPattern = new vscode.RelativePattern(bridgeDir, '*.codex-trigger');
    codexWatcher = vscode.workspace.createFileSystemWatcher(codexPattern);
    codexWatcher.onDidCreate(handleCodexTrigger);
    codexWatcher.onDidChange(handleCodexTrigger);
    context.subscriptions.push(codexWatcher);

    updateStatus('$(plug) Claude Bridge');
    console.log(`Claude Bridge: 감시 시작 → ${bridgeDir} (.trigger + .codex-trigger)`);

    // 이미 존재하는 트리거 파일 처리
    const existing = fs.readdirSync(bridgeDir);
    for (const file of existing) {
        if (file.endsWith('.codex-trigger')) {
            handleCodexTrigger(vscode.Uri.file(path.join(bridgeDir, file)));
        } else if (file.endsWith('.trigger')) {
            handleGeminiTrigger(vscode.Uri.file(path.join(bridgeDir, file)));
        }
    }
}

function startBridgeDirWatcher(context) {
    stopBridgeDirWatcher();
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) return;

    for (const folder of folders) {
        const pattern = new vscode.RelativePattern(folder, 'bridge/from-claude/*');
        bridgeDirWatcher = vscode.workspace.createFileSystemWatcher(pattern);
        bridgeDirWatcher.onDidCreate(() => {
            console.log('Claude Bridge: bridge/from-claude/ 감지됨, watcher 전환');
            stopBridgeDirWatcher();
            setupWatchers(context);
        });
        context.subscriptions.push(bridgeDirWatcher);
    }
}

function stopBridgeDirWatcher() {
    if (bridgeDirWatcher) { bridgeDirWatcher.dispose(); bridgeDirWatcher = null; }
}

function disposeWatchers() {
    if (watcher) { watcher.dispose(); watcher = null; }
    if (codexWatcher) { codexWatcher.dispose(); codexWatcher = null; }
    stopBridgeDirWatcher();
}

function deactivate() {
    disposeWatchers();
    stopResponseWatch();
    stopAutoApprove();
    console.log('Claude Bridge 익스텐션 비활성화됨');
}

module.exports = { activate, deactivate };
