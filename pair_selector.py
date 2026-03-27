"""Before/After ペア選択 Web アプリ"""

import io
import json
import base64
from pathlib import Path
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template_string, request, jsonify, send_file

from chat_api import get_credentials
from googleapiclient.discovery import build
from story_maker import create_story_image

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "image_cache"
CONFIG_PATH = BASE_DIR / "config.json"

JST = timezone(timedelta(hours=9))
DRIVE_FOLDER_ID = "0AOfsgg1fAZ18Uk9PVA"

app = Flask(__name__)

# グローバルにDriveサービスを保持
_drive_service = None
_creds = None


def get_drive():
    global _drive_service, _creds
    if _drive_service is None:
        _creds = get_credentials()
        _drive_service = build("drive", "v3", credentials=_creds)
    return _drive_service


def list_drive_images():
    """Driveフォルダ内の画像一覧を取得し、メッセージ単位でグループ化する"""
    drive = get_drive()
    all_files = []
    page_token = None

    while True:
        results = drive.files().list(
            q=f"'{DRIVE_FOLDER_ID}' in parents and mimeType contains 'image/'",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="nextPageToken, files(id, name, createdTime, thumbnailLink)",
            pageSize=200,
            pageToken=page_token,
        ).execute()
        all_files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    # ファイル名のプレフィックス(日時_投稿者)でグループ化
    groups = {}
    for f in all_files:
        name = f["name"]
        # "20260106_0716_unknown_298.jpeg" → "20260106_0716_unknown"
        parts = name.rsplit("_", 1)
        group_key = parts[0] if len(parts) > 1 else name
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(f)

    # グループをソート（新しい順）
    sorted_groups = sorted(groups.items(), key=lambda x: x[0], reverse=True)
    return sorted_groups


def download_image(file_id):
    """Drive画像をダウンロードしてキャッシュする"""
    import time
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"{file_id}.jpg"

    if cache_path.exists():
        return cache_path

    for attempt in range(3):
        try:
            drive = get_drive()
            content = drive.files().get_media(
                fileId=file_id, supportsAllDrives=True
            ).execute()

            with open(cache_path, "wb") as f:
                f.write(content)

            return cache_path
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
            else:
                raise e


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Before/After ペア選択</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, sans-serif; background: #1a1a1a; color: #fff; padding: 20px; }
h1 { text-align: center; margin-bottom: 20px; font-size: 24px; }

.group {
    background: #2a2a2a; border-radius: 12px; padding: 16px;
    margin-bottom: 20px;
}
.group-header {
    font-size: 14px; color: #aaa; margin-bottom: 12px;
    display: flex; justify-content: space-between; align-items: center;
}
.group-images {
    display: flex; flex-wrap: wrap; gap: 8px;
}
.img-card {
    position: relative; cursor: pointer; border-radius: 8px;
    overflow: hidden; border: 3px solid transparent;
    transition: border-color 0.2s; width: 180px; height: 180px;
}
.img-card img {
    width: 100%; height: 100%; object-fit: cover;
}
.img-card.selected-before { border-color: #ff4444; }
.img-card.selected-after { border-color: #44aaff; }
.img-card .label {
    position: absolute; top: 4px; left: 4px; padding: 2px 8px;
    border-radius: 4px; font-size: 12px; font-weight: bold;
    display: none;
}
.img-card.selected-before .label {
    display: block; background: #ff4444; color: #fff;
}
.img-card.selected-after .label {
    display: block; background: #44aaff; color: #fff;
}

.controls {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #333; padding: 16px 20px;
    display: flex; align-items: center; gap: 12px;
    border-top: 1px solid #555;
}
.controls input {
    flex: 1; padding: 10px; border-radius: 8px; border: none;
    font-size: 16px; background: #444; color: #fff;
}
.controls button {
    padding: 10px 24px; border-radius: 8px; border: none;
    font-size: 16px; font-weight: bold; cursor: pointer;
    background: #6cb92d; color: #fff;
}
.controls button:disabled {
    background: #555; color: #888; cursor: default;
}
.controls .hint {
    color: #aaa; font-size: 13px; min-width: 200px;
}

.result {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.95); display: none;
    z-index: 100; overflow-y: auto;
}
.editor {
    display: flex; align-items: flex-start; justify-content: center;
    gap: 20px; padding: 20px; min-height: 100%;
}
.editor canvas {
    border-radius: 8px; cursor: grab; flex-shrink: 0;
}
.editor canvas:active { cursor: grabbing; }
.editor-panel {
    display: flex; flex-direction: column; gap: 8px; min-width: 260px;
    padding: 10px;
    max-height: 100vh;
    overflow-y: auto;
}
.editor-panel h3 { color: #fff; font-size: 16px; margin: 0; }
.editor-panel button {
    padding: 10px 24px; border-radius: 8px; border: none;
    font-size: 16px; cursor: pointer; width: 100%;
}
.btn-close { background: #555; color: #fff; }
.btn-download { background: #6cb92d; color: #fff; font-weight: bold; }
.slider-group {
    display: flex; flex-direction: column; gap: 2px;
}
.slider-group label { color: #aaa; font-size: 13px; }
.slider-group input[type=range] { width: 100%; }
.slider-group input[type=text] {
    width: 100%; padding: 8px; border-radius: 6px; border: none;
    font-size: 15px; background: #444; color: #fff;
}
.slider-group .val { color: #fff; font-size: 12px; text-align: right; }
.drag-hint { color: #888; font-size: 12px; text-align: center; }

.mode-indicator {
    position: fixed; top: 20px; right: 20px;
    padding: 8px 16px; border-radius: 8px; font-weight: bold;
    z-index: 50; font-size: 14px;
}
.mode-before { background: #ff4444; }
.mode-after { background: #44aaff; }

body { padding-bottom: 80px; }
</style>
</head>
<body>

<h1>Before / After ペア選択</h1>
<p style="text-align:center;color:#aaa;margin-bottom:20px;">
    1. Before写真をクリック → 2. After写真をクリック → 3. 生成 → 4. 編集・ダウンロード
</p>

<div id="mode-indicator" class="mode-indicator mode-before">Before を選択</div>

<div id="groups"></div>

<div class="controls">
    <div class="hint" id="hint">Before写真を選んでください</div>
    <button id="generate-btn" disabled onclick="generate()">生成</button>
</div>

<div class="result" id="result">
    <div class="editor">
        <canvas id="preview" width="540" height="960"></canvas>
        <div class="editor-panel" id="editor-panel">
            <div class="slider-group">
                <label>タイトル</label>
                <input type="text" id="title" placeholder="タイトル（例: 洗濯機分解洗浄）" oninput="renderPreview()" />
            </div>

            <h3>Before</h3>
            <div class="slider-group">
                <label>ズーム <span id="before-zoom-val">1.0x</span></label>
                <input type="range" id="before-zoom" min="1.0" max="5.0" step="0.05" value="1.0" oninput="updateSliderVal(this, 'before-zoom-val', 'x'); renderPreview()">
            </div>
            <div class="slider-group">
                <label>回転 <span id="before-rotate-val">0°</span></label>
                <input type="range" id="before-rotate" min="-180" max="180" step="1" value="0" oninput="document.getElementById('before-rotate-val').textContent = this.value + '°'; renderPreview()">
            </div>
            <div id="before-adjustments"></div>
            <p class="drag-hint">ドラッグで位置調整</p>

            <h3>After</h3>
            <div class="slider-group">
                <label>ズーム <span id="after-zoom-val">1.0x</span></label>
                <input type="range" id="after-zoom" min="1.0" max="5.0" step="0.05" value="1.0" oninput="updateSliderVal(this, 'after-zoom-val', 'x'); renderPreview()">
            </div>
            <div class="slider-group">
                <label>回転 <span id="after-rotate-val">0°</span></label>
                <input type="range" id="after-rotate" min="-180" max="180" step="1" value="0" oninput="document.getElementById('after-rotate-val').textContent = this.value + '°'; renderPreview()">
            </div>
            <div id="after-adjustments"></div>
            <p class="drag-hint">ドラッグで位置調整</p>

            <button class="btn-download" onclick="downloadImage()">ダウンロード</button>
            <button class="btn-close" onclick="closeResult()">閉じる</button>
        </div>
    </div>
</div>

<script>
let selectedBefore = null;
let selectedAfter = null;
let mode = 'before';

const ADJUSTMENTS = [
    {id: 'exposure', label: '露出'},
    {id: 'highlights', label: 'ハイライト'},
    {id: 'shadows', label: 'シャドウ'},
    {id: 'contrast', label: 'コントラスト'},
    {id: 'brightness', label: '明るさ'},
    {id: 'blackpoint', label: 'ブラックポイント'},
    {id: 'saturation', label: '彩度'},
    {id: 'vibrance', label: '自然な彩度'},
    {id: 'warmth', label: '温かみ'},
    {id: 'tint', label: '色合い'},
];

function createAdjustmentSliders(prefix, containerId) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    ADJUSTMENTS.forEach(adj => {
        const div = document.createElement('div');
        div.className = 'slider-group';
        const sliderId = prefix + '-' + adj.id;
        var valSpanId = sliderId + '-val';
        div.innerHTML =
            '<label>' + adj.label + ' <span id="' + valSpanId + '">0</span></label>' +
            '<input type="range" id="' + sliderId + '" min="-100" max="100" step="1" value="0">';
        div.querySelector('input').addEventListener('input', (function(vid) {
            return function() {
                document.getElementById(vid).textContent = this.value;
                renderPreview();
            };
        })(valSpanId));
        container.appendChild(div);
    });
}

createAdjustmentSliders('before', 'before-adjustments');
createAdjustmentSliders('after', 'after-adjustments');

async function loadGroups() {
    const res = await fetch('/api/groups');
    const groups = await res.json();
    const container = document.getElementById('groups');

    groups.forEach(([key, files]) => {
        const div = document.createElement('div');
        div.className = 'group';

        const dateStr = key.substring(0, 8);
        const formatted = dateStr.substring(0,4) + '/' + dateStr.substring(4,6) + '/' + dateStr.substring(6,8);

        div.innerHTML = `
            <div class="group-header">
                <span>${formatted} (${files.length}枚)</span>
            </div>
            <div class="group-images">
                ${files.map(f => `
                    <div class="img-card" data-id="${f.id}" data-name="${f.name}" onclick="selectImage(this)">
                        <img src="/api/thumbnail/${f.id}" loading="lazy" />
                        <div class="label"></div>
                    </div>
                `).join('')}
            </div>
        `;
        container.appendChild(div);
    });
}

function selectImage(el) {
    const id = el.dataset.id;
    const name = el.dataset.name;

    if (mode === 'before') {
        // 前のBefore選択を解除
        document.querySelectorAll('.selected-before').forEach(e => {
            e.classList.remove('selected-before');
            e.querySelector('.label').textContent = '';
        });
        el.classList.add('selected-before');
        el.querySelector('.label').textContent = 'Before';
        selectedBefore = id;
        mode = 'after';
        updateUI();
    } else {
        // 前のAfter選択を解除
        document.querySelectorAll('.selected-after').forEach(e => {
            e.classList.remove('selected-after');
            e.querySelector('.label').textContent = '';
        });
        el.classList.add('selected-after');
        el.querySelector('.label').textContent = 'After';
        selectedAfter = id;
        updateUI();
    }
}

function updateUI() {
    const indicator = document.getElementById('mode-indicator');
    const hint = document.getElementById('hint');
    const btn = document.getElementById('generate-btn');

    if (mode === 'before') {
        indicator.className = 'mode-indicator mode-before';
        indicator.textContent = 'Before を選択';
        hint.textContent = 'Before写真を選んでください';
    } else if (!selectedAfter) {
        indicator.className = 'mode-indicator mode-after';
        indicator.textContent = 'After を選択';
        hint.textContent = 'After写真を選んでください';
    } else {
        indicator.className = 'mode-indicator mode-after';
        indicator.textContent = '準備完了';
        hint.textContent = '生成ボタンを押してください';
    }

    btn.disabled = !(selectedBefore && selectedAfter);
}

// エディタ用
let beforeImg = null, afterImg = null, templateImg = null, logoImg = null;
let beforeOffset = {x:0, y:0}, afterOffset = {x:0, y:0};
let dragging = null, dragStart = {x:0, y:0}, dragOffsetStart = {x:0, y:0};

// テンプレート上の写真エリア (1080x1920 の座標)
const BEFORE_AREA = {x:0, y:0, w:1080, h:791};
const AFTER_AREA = {x:0, y:1129, w:1080, h:791};

async function generate() {
    const btn = document.getElementById('generate-btn');
    btn.disabled = true;
    btn.textContent = '読込中...';

    // 画像とテンプレートを読み込み
    beforeImg = await loadImage('/api/thumbnail/' + selectedBefore);
    afterImg = await loadImage('/api/thumbnail/' + selectedAfter);
    if (!templateImg) templateImg = await loadImage('/api/template');

    // ロゴ読み込み
    if (!logoImg) logoImg = await loadImage('/api/logo');

    // オフセットリセット
    beforeOffset = {x:0, y:0};
    afterOffset = {x:0, y:0};

    // スライダーリセット
    document.getElementById('before-zoom').value = 1.0;
    document.getElementById('after-zoom').value = 1.0;
    document.getElementById('before-zoom-val').textContent = '1.0x';
    document.getElementById('after-zoom-val').textContent = '1.0x';
    document.getElementById('before-rotate').value = 0;
    document.getElementById('after-rotate').value = 0;
    document.getElementById('before-rotate-val').textContent = '0°';
    document.getElementById('after-rotate-val').textContent = '0°';
    // 調整スライダーをリセット
    ['before', 'after'].forEach(prefix => {
        ADJUSTMENTS.forEach(adj => {
            const el = document.getElementById(prefix + '-' + adj.id);
            if (el) { el.value = 0; }
            const valEl = document.getElementById(prefix + '-' + adj.id + '-val');
            if (valEl) { valEl.textContent = '0'; }
        });
    });

    document.getElementById('result').style.display = 'block';
    renderPreview();

    btn.disabled = false;
    btn.textContent = '生成';
}

function loadImage(src) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = src;
    });
}

function updateSliderVal(el, valId, suffix, mult) {
    const v = parseFloat(el.value);
    const display = mult ? Math.round(v * mult) : v.toFixed(1);
    document.getElementById(valId).textContent = display + suffix;
}

function getAdjustments(prefix) {
    const adj = {};
    ADJUSTMENTS.forEach(a => {
        adj[a.id] = parseInt(document.getElementById(prefix + '-' + a.id).value) || 0;
    });
    return adj;
}

function applyAdjustments(ctx, x, y, w, h, adj) {
    if (ADJUSTMENTS.every(a => (adj[a.id] || 0) === 0)) return;

    const imageData = ctx.getImageData(x, y, w, h);
    const d = imageData.data;
    const len = d.length;

    const expF = adj.exposure ? Math.pow(2, adj.exposure / 100) : 1;
    const brightAdd = (adj.brightness || 0) * 2.55;
    const contF = 1 + (adj.contrast || 0) / 100;

    for (let i = 0; i < len; i += 4) {
        let r = d[i], g = d[i+1], b = d[i+2];

        // 露出
        if (adj.exposure) { r *= expF; g *= expF; b *= expF; }

        // 明るさ
        if (adj.brightness) { r += brightAdd; g += brightAdd; b += brightAdd; }

        // コントラスト
        if (adj.contrast) {
            r = (r - 128) * contF + 128;
            g = (g - 128) * contF + 128;
            b = (b - 128) * contF + 128;
        }

        // ブラックポイント
        if (adj.blackpoint) {
            var bp = adj.blackpoint * 1.275;
            if (bp > 0) {
                r = bp + r * (255 - bp) / 255;
                g = bp + g * (255 - bp) / 255;
                b = bp + b * (255 - bp) / 255;
            } else {
                var f = 1 + bp / 255;
                r *= Math.max(0, f); g *= Math.max(0, f); b *= Math.max(0, f);
            }
        }

        // ハイライト
        if (adj.highlights) {
            var luma = 0.299 * r + 0.587 * g + 0.114 * b;
            if (luma > 128) {
                var amt = (luma - 128) / 127;
                var shift = adj.highlights * 1.275 * amt;
                r += shift; g += shift; b += shift;
            }
        }

        // シャドウ
        if (adj.shadows) {
            var luma2 = 0.299 * r + 0.587 * g + 0.114 * b;
            if (luma2 < 128) {
                var amt2 = 1 - luma2 / 128;
                var shift2 = adj.shadows * 1.275 * amt2;
                r += shift2; g += shift2; b += shift2;
            }
        }

        // 彩度
        if (adj.saturation) {
            var gray = 0.299 * r + 0.587 * g + 0.114 * b;
            var sf = 1 + adj.saturation / 100;
            r = gray + (r - gray) * sf;
            g = gray + (g - gray) * sf;
            b = gray + (b - gray) * sf;
        }

        // 自然な彩度
        if (adj.vibrance) {
            var maxC = Math.max(r, g, b);
            var minC = Math.min(r, g, b);
            var sat = maxC > 0 ? (maxC - minC) / maxC : 0;
            var vAmt = (1 - sat) * (adj.vibrance / 100);
            var vGray = 0.299 * r + 0.587 * g + 0.114 * b;
            r = vGray + (r - vGray) * (1 + vAmt);
            g = vGray + (g - vGray) * (1 + vAmt);
            b = vGray + (b - vGray) * (1 + vAmt);
        }

        // 温かみ
        if (adj.warmth) {
            var ww = adj.warmth / 100 * 30;
            r += ww; b -= ww;
        }

        // 色合い
        if (adj.tint) {
            var tt = adj.tint / 100 * 30;
            g -= tt; r += tt * 0.5; b += tt * 0.5;
        }

        d[i] = Math.max(0, Math.min(255, r));
        d[i+1] = Math.max(0, Math.min(255, g));
        d[i+2] = Math.max(0, Math.min(255, b));
    }
    ctx.putImageData(imageData, x, y);
}

function drawPhoto(ctx, img, area, zoom, offset, rotateDeg) {
    const imgRatio = img.width / img.height;
    const areaRatio = area.w / area.h;

    let sw, sh;
    if (imgRatio > areaRatio) {
        sh = img.height / zoom;
        sw = sh * areaRatio;
    } else {
        sw = img.width / zoom;
        sh = sw / areaRatio;
    }

    const maxOffX = (img.width - sw) / 2;
    const maxOffY = (img.height - sh) / 2;
    const ox = Math.max(-maxOffX, Math.min(maxOffX, offset.x * img.width / area.w));
    const oy = Math.max(-maxOffY, Math.min(maxOffY, offset.y * img.height / area.h));

    const sx = (img.width - sw) / 2 - ox;
    const sy = (img.height - sh) / 2 - oy;

    if (rotateDeg && rotateDeg !== 0) {
        ctx.save();
        var cx = area.x + area.w / 2;
        var cy = area.y + area.h / 2;
        ctx.translate(cx, cy);
        ctx.rotate(rotateDeg * Math.PI / 180);
        // 回転時に隙間ができないよう拡大
        var rad = Math.abs(rotateDeg * Math.PI / 180);
        var cos = Math.cos(rad), sin = Math.sin(rad);
        var scale = Math.max(
            (area.w * cos + area.h * sin) / area.w,
            (area.w * sin + area.h * cos) / area.h
        );
        ctx.scale(scale, scale);
        ctx.drawImage(img, sx, sy, sw, sh, -area.w / 2, -area.h / 2, area.w, area.h);
        ctx.restore();
    } else {
        ctx.drawImage(img, sx, sy, sw, sh, area.x, area.y, area.w, area.h);
    }
}

function renderPreview() {
    if (!beforeImg || !afterImg || !templateImg) return;

    const canvas = document.getElementById('preview');
    const ctx = canvas.getContext('2d');
    const scale = canvas.width / 1080;

    // 内部は1080x1920で描画
    canvas.width = 1080;
    canvas.height = 1920;
    canvas.style.width = '400px';
    canvas.style.height = Math.round(400 * 1920 / 1080) + 'px';

    const bZoom = parseFloat(document.getElementById('before-zoom').value);
    const aZoom = parseFloat(document.getElementById('after-zoom').value);
    const bRotate = parseInt(document.getElementById('before-rotate').value) || 0;
    const aRotate = parseInt(document.getElementById('after-rotate').value) || 0;
    const bAdj = getAdjustments('before');
    const aAdj = getAdjustments('after');

    // 白背景
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, 1080, 1920);

    // Before写真
    drawPhoto(ctx, beforeImg, BEFORE_AREA, bZoom, beforeOffset, bRotate);
    applyAdjustments(ctx, BEFORE_AREA.x, BEFORE_AREA.y, BEFORE_AREA.w, BEFORE_AREA.h, bAdj);

    // After写真
    drawPhoto(ctx, afterImg, AFTER_AREA, aZoom, afterOffset, aRotate);
    applyAdjustments(ctx, AFTER_AREA.x, AFTER_AREA.y, AFTER_AREA.w, AFTER_AREA.h, aAdj);

    // テンプレートオーバーレイ
    ctx.drawImage(templateImg, 0, 0, 1080, 1920);

    // ロゴ描画（白縁付き）
    if (logoImg) {
        const logoW = 530;
        const logoH = Math.round(logoImg.height * (logoW / logoImg.width));
        const logoX = 768 - logoW / 2;
        const logoY = 1920 - logoH - 51;

        // 白縁: ロゴを周囲にずらして白く描画
        const outW = 16;
        const tmpC = document.createElement('canvas');
        tmpC.width = logoImg.width; tmpC.height = logoImg.height;
        const tmpCtx = tmpC.getContext('2d');
        tmpCtx.drawImage(logoImg, 0, 0);
        // 白シルエット作成
        const silC = document.createElement('canvas');
        silC.width = logoImg.width; silC.height = logoImg.height;
        const silCtx = silC.getContext('2d');
        silCtx.drawImage(logoImg, 0, 0);
        silCtx.globalCompositeOperation = 'source-in';
        silCtx.fillStyle = '#fff';
        silCtx.fillRect(0, 0, silC.width, silC.height);

        for (let dx = -outW; dx <= outW; dx += 2) {
            for (let dy = -outW; dy <= outW; dy += 2) {
                if (dx*dx + dy*dy <= outW*outW) {
                    ctx.drawImage(silC, logoX + dx, logoY + dy, logoW, logoH);
                }
            }
        }
        ctx.drawImage(logoImg, logoX, logoY, logoW, logoH);
    }

    // タイトルテキスト
    const title = document.getElementById('title').value || '清掃';
    ctx.font = '70px "Hiragino Kaku Gothic ProN", sans-serif';
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(title, 530 + (1080 - 530) / 2, 846 + 30);
}

// ドラッグで位置調整
const previewCanvas = document.getElementById('preview');
previewCanvas.addEventListener('mousedown', (e) => {
    const rect = previewCanvas.getBoundingClientRect();
    const scaleX = 1080 / rect.width;
    const y = (e.clientY - rect.top) * scaleX;

    if (y < 791) {
        dragging = 'before';
    } else if (y > 1129) {
        dragging = 'after';
    } else {
        return;
    }
    dragStart = {x: e.clientX, y: e.clientY};
    dragOffsetStart = dragging === 'before' ? {...beforeOffset} : {...afterOffset};
    e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const rect = previewCanvas.getBoundingClientRect();
    const scale = 1080 / rect.width;
    const dx = (e.clientX - dragStart.x) * scale;
    const dy = (e.clientY - dragStart.y) * scale;

    if (dragging === 'before') {
        beforeOffset = {x: dragOffsetStart.x + dx, y: dragOffsetStart.y + dy};
    } else {
        afterOffset = {x: dragOffsetStart.x + dx, y: dragOffsetStart.y + dy};
    }
    renderPreview();
});

window.addEventListener('mouseup', () => { dragging = null; });

function downloadImage() {
    // サーバー側で高品質生成
    const title = document.getElementById('title').value || '清掃';
    const bAdj = getAdjustments('before');
    const aAdj = getAdjustments('after');
    const body = {
        before_id: selectedBefore,
        after_id: selectedAfter,
        title: title,
        before_zoom: parseFloat(document.getElementById('before-zoom').value),
        after_zoom: parseFloat(document.getElementById('after-zoom').value),
        before_rotate: parseInt(document.getElementById('before-rotate').value) || 0,
        after_rotate: parseInt(document.getElementById('after-rotate').value) || 0,
        before_offset_x: beforeOffset.x,
        before_offset_y: beforeOffset.y,
        after_offset_x: afterOffset.x,
        after_offset_y: afterOffset.y,
        before_adjustments: bAdj,
        after_adjustments: aAdj,
    };
    fetch('/api/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    }).then(r => r.json()).then(data => {
        if (data.success) {
            const a = document.createElement('a');
            a.href = '/api/output/' + data.filename;
            a.download = data.filename;
            a.click();
        } else {
            alert('エラー: ' + data.error);
        }
    });
}

function closeResult() {
    document.getElementById('result').style.display = 'none';
    selectedBefore = null;
    selectedAfter = null;
    mode = 'before';
    document.querySelectorAll('.selected-before, .selected-after').forEach(e => {
        e.classList.remove('selected-before', 'selected-after');
        e.querySelector('.label').textContent = '';
    });
    updateUI();
}

loadGroups();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/groups")
def api_groups():
    groups = list_drive_images()
    # 画像が2枚以上のグループのみ返す
    result = []
    for key, files in groups:
        if len(files) >= 2:
            result.append((key, [{"id": f["id"], "name": f["name"]} for f in files]))
    return jsonify(result)


@app.route("/api/thumbnail/<file_id>")
def api_thumbnail(file_id):
    path = download_image(file_id)
    return send_file(str(path), mimetype="image/jpeg")


@app.route("/api/logo")
def api_logo():
    return send_file(str(BASE_DIR / "logo.png"), mimetype="image/png")


@app.route("/api/template")
def api_template():
    return send_file(str(BASE_DIR / "template.png"), mimetype="image/png")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json
    before_id = data["before_id"]
    after_id = data["after_id"]
    title = data["title"]

    try:
        before_path = download_image(before_id)
        after_path = download_image(after_id)

        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
        filename = f"story_{timestamp}.jpg"
        output_path = OUTPUT_DIR / filename

        create_story_image(
            str(before_path), str(after_path), title, str(output_path),
            before_zoom=data.get("before_zoom", 1.0),
            after_zoom=data.get("after_zoom", 1.0),
            before_rotate=data.get("before_rotate", 0),
            after_rotate=data.get("after_rotate", 0),
            before_offset_x=data.get("before_offset_x", 0),
            before_offset_y=data.get("before_offset_y", 0),
            after_offset_x=data.get("after_offset_x", 0),
            after_offset_y=data.get("after_offset_y", 0),
            before_adjustments=data.get("before_adjustments", {}),
            after_adjustments=data.get("after_adjustments", {}),
        )

        return jsonify({"success": True, "filename": filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/output/<filename>")
def api_output(filename):
    path = OUTPUT_DIR / filename
    return send_file(str(path), mimetype="image/jpeg")


if __name__ == "__main__":
    print("ブラウザで http://localhost:5050 を開いてください")
    app.run(port=5050, debug=False)
