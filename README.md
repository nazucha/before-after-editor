# Before/After Editor（静的サイト版）

Instagram ストーリーズ用の Before/After 画像を作成するツールです。
サーバー不要で、ブラウザだけで動作します。

## セットアップ

### 1. Google Cloud OAuth クライアント ID の作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 既存プロジェクト（cleaning app で使っているもの）を選択
3. **APIとサービス** → **認証情報** → **認証情報を作成** → **OAuth クライアント ID**
4. アプリケーションの種類: **ウェブ アプリケーション**
5. **承認済みの JavaScript 生成元** に以下を追加:
   - ローカルテスト用: `http://localhost:8080`（任意のポート）
   - 本番用: デプロイ先の URL
6. 作成後、**クライアント ID** をコピー

### 2. Google Drive API の有効化

1. **APIとサービス** → **ライブラリ**
2. 「Google Drive API」を検索して **有効にする**

### 3. クライアント ID の設定

`index.html` 内の `CONFIG.CLIENT_ID` を取得したクライアント ID に書き換え:

```javascript
const CONFIG = {
    CLIENT_ID: 'xxxxxxxxxxxx.apps.googleusercontent.com',  // ← ここ
    FOLDER_ID: '0AOfsgg1fAZ18Uk9PVA',
};
```

### 4. ローカルで動作確認

```bash
# Python の場合
python3 -m http.server 8080

# Node.js の場合
npx serve -p 8080
```

ブラウザで `http://localhost:8080` を開く。

## デプロイ方法

サーバーサイド処理は不要なので、静的ホスティングならどこでもOKです。

### 方法 A: Railway（既存プロジェクトに追加）

Railway の Static Site として追加デプロイ可能ですが、別プロジェクトにする方が管理しやすいです。

### 方法 B: Cloudflare Pages（無料・おすすめ）

1. GitHub にこのリポジトリを push
2. [Cloudflare Pages](https://pages.cloudflare.com/) でリポジトリを接続
3. ビルド設定: なし（そのまま配信）
4. デプロイ完了後の URL を OAuth の「承認済み JavaScript 生成元」に追加

### 方法 C: GitHub Pages（無料）

1. リポジトリの Settings → Pages
2. Source: Deploy from a branch → `main` / `/ (root)`
3. デプロイ完了後の URL を OAuth の「承認済み JavaScript 生成元」に追加

## 必要なファイル

デプロイ時に含めるファイル:

```
index.html      ← メインアプリ
template.png    ← テンプレート画像
logo.png        ← ロゴ画像
```

## 旧ファイル（不要）

以下は Flask サーバー版のファイルです。静的サイト版では不要です:

- `pair_selector.py`
- `story_maker.py`
- `chat_api.py`
- `config.json`
