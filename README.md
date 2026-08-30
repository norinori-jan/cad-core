# cad-core — Sketchレビュー対応セッション記録(README-session.mdへの追記)

前回セッション(README-session.md)からの変更点。**cadqueryが手元で実行できない環境で作成した
ため、このセッションの変更は未検証。ローカルでの実行確認が必須。**

## 実装方式の変更(README-session.mdの記述は古い)

README-session.mdには「2D合成専用のcq.Sketchクラス(mode='a')を使う」とあるが、これは古い。
現在は完全に手動の

```
Basic Geometry(line/circle/arc)
  → (rectangle/polygonはlineへnormalize)
  → 端点を突き合わせてWireをトレース
  → outer/innerを判定してFace.makeFromWires()で穴あきProfile構築
  → Solid.extrudeLinear()でextrude
```

という方式に置き換わっている。`build_profile()`の戻り値は`cq.Sketch`ではなく`cq.Face`。

## 今回のレビューで見つかった問題と対応

| 問題 | 対応 |
|---|---|
| arcの角度計算が`(a0+a1)/2`で、350°→10°のような0°またぎで破綻 | `(a1-a0)%360`でCCW sweepを正規化し、`mid_angle = a0 + sweep/2`に修正。sweep=0(start==end)はSketchError(full circleはtype="circle"を使う) |
| 複数loopの内包判定が「最大bbox以外は全部inner」で3階層以上のネストも受け入れてしまっていた | 全loopペアでbbox内包関係のグラフを作り、内包される回数が2以上(3階層以上)ならSketchError。outerが1つに定まらない/outerに内包されないloopがある場合もSketchError |
| line/arcの端点接続が、同一点に複数辺がある場合に「最初に見つかった辺」を勝手に選んでいた | トレース前に全端点の接続数を検証。未接続(0個)・分岐(2個以上)を検出したらトレース前にSketchError |
| radius/width/height/polygon面積/line長のゼロ・負値チェックが無かった | 各geometryビルダーに追加(circle/arcのradius>0、rectangleのwidth/height>0、polygonの面積(shoelace公式)>0、lineのstart≠end) |
| units(mm以外)が実質無視されていた | `build_from_dict()`で`units != "mm"`ならGeometryError |
| extrude distance=0を許してしまっていた | `distance == 0`ならGeometryError(正負は許可: +Z/-Z方向) |
| operationのresult_id省略を許していた(依存関係が曖昧になる) | 全operationでresult_id必須に変更 |

## 今回は対応しなかったもの(意図的に見送り)

- **Sketchのposition/rotation**: 今回は実装しない。Phase 2として仕様上明確に切り離す方針。
  現状は常に世界XY平面・原点・+Z方向extrudeのみ(`plane != "XY"`はSketchError、変更なし)。
- **bbox基準の内包判定**: 真の点in多角形判定ではなく簡易判定のまま。凹形状などで誤判定の
  可能性がある既知の制限として残している。
- **fillet/chamferの全edge選択問題**: Selection.pyとの正式接続時に対応する範囲として据え置き。

## 追加した検証用JSON(すべて未実行・理論値のみ計算済み)

| ファイル | 内容 | 理論値 |
|---|---|---|
| `sketch_square_with_hole.json` | rectangle(outer)+circle(inner穴) | volume≈15214.601836 |
| `sketch_line_triangle.json` | line3本の複合ワイヤ(三角形) | volume=1500 |
| `sketch_arc_wraparound.json` | arc(350°→10°)を含む扇形。0°またぎのCCW sweep修正の検証用 | volume≈87.266463 |
| `sketch_line_arc_dshape.json` | line1本+arc1本(半円)のDシェイプ | volume≈1256.637061 |
| `sketch_multi_hole.json` | outer rectangle+独立した2つのcircle穴 | volume≈6973.805329 |
| `sketch_rect_hole_rect.json` | outer rectangle+inner rectangle穴 | volume=9000 |
| `err_open_line.json` | line2本のみ(閉じない) | SketchError期待 |
| `err_branching_line.json` | 1点に3本のlineが集まる分岐 | SketchError期待 |
| `err_zero_radius.json` | circle radius=0 | SketchError期待 |
| `err_nested_island.json` | outer>hole>islandの3階層ネスト | SketchError期待 |
| `err_zero_extrude.json` | 正常なsketchだがdistance=0 | GeometryError期待 |
| `err_degenerate_polygon.json` | 3点が一直線上のpolygon(面積ゼロ) | SketchError期待 |

既存の回帰テスト(box/boolean/torus/fillet/chamfer、および前回の`sketch_extrude_subtract.json`)も
併せて実行し、result_id必須化やunits='mm'固定によって既存JSONが壊れていないか確認すること。
