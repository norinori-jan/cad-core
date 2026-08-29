# CAD Core Engine — 雛形

flow-mind / quick-ref から構造化されたパラメータ辞書（JSON）を受け取り、
実際のC++幾何カーネル（OCCT）で3Dモデルを生成・ブーリアン加工・検証する、
疎結合設計の最小構成。**このチャット環境上で実際に動作確認済み。**

## なぜこの構成なのか

「Pythonだけで本格的なCADは作れない」——これはB-repブーリアン演算・
NURBS処理の数値安定性がC++実装（Parasolid/ACIS/OCCT等）でしか
実用レベルに到達しないため。このプロジェクトは「PythonでCADカーネルを
書く」のではなく「実在するC++幾何カーネル(OCCT)をPythonから正しく叩く」
構成にしている。`cadquery`ライブラリが、その橋渡し（Pythonバインディング）。

## ディレクトリ構成

```
cad-core/
├── core/
│   └── engine.py       ← 幾何計算の本体(パラメータ辞書→形状→検証→メッシュ/STEP/STL)
├── api/
│   └── server.py        ← flow-mind/quick-refとの境界(FastAPI, 固定トークン認証)
├── examples/
│   └── box_with_hole.json  ← パラメータ辞書の実例
├── requirements.txt
└── README.md (このファイル)
```

## セットアップ

```bash
pip install -r requirements.txt
```

macOS/Windowsでは `pip install cadquery` だけで、内部のOCCT(C++)込みの
バイナリが一緒にインストールされる（ビルド不要）。

## 起動

```bash
export CAD_ENGINE_TOKEN="自分だけのトークンに変更"
uvicorn api.server:app --reload --port 8420
```

## 動作確認（このチャット環境で実際に検証済みの手順）

```bash
curl -X POST http://127.0.0.1:8420/api/build \
  -H "Content-Type: application/json" \
  -d @examples/box_with_hole.json
```

100mm×100mm×100mmの箱から半径30mmの穴を貫通させた形状が生成され、
体積717256.66mm³・メッシュ頂点530個・三角形520個が返ってくることを確認済み。

## パラメータ辞書の形（flow-mind/quick-refとの契約）

```json
{
  "units": "mm",
  "primitives": [
    {"id": "base", "type": "box",      "params": {"length": 100, "width": 100, "height": 100}},
    {"id": "hole", "type": "cylinder", "params": {"radius": 30, "height": 120}}
  ],
  "operations": [
    {"op": "cut", "base": "base", "tool": "hole", "result_id": "part1"}
  ]
}
```

- 対応プリミティブ: `box` / `cylinder` / `sphere`（今後追加していく前提の最小セット）
- 対応演算: `cut`（差）/ `union`（和）/ `intersect`（積）
- **自然言語解析・音声認識・意図解釈はこのエンジンでは一切行わない。**
  それらは全てflow-mind/quick-ref側の責務であり、この境界の外側にある。

## エンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/health` | 死活確認 |
| POST | `/api/build` | パラメータ辞書→メッシュ+メタデータ(JSON)。Swift側でのプレビュー向け |
| POST | `/api/build/export?fmt=step\|stl` | パラメータ辞書→ファイル出力。他CADソフト/3Dプリント向け |

## 今後の拡張候補（優先度は未確定・都度相談すること）

- プリミティブの追加（extrude, sweep, fillet, chamfer等）
- アセンブリ機能（複数部品間の本格的な干渉チェック）
- flow-mindのノードとしてCAD形状を取り込む連携（他のブリッジと同じ設計パターンを踏襲する想定）
- Swift側（RealityKit/SceneKit）のビューア実装は本リポジトリの範囲外