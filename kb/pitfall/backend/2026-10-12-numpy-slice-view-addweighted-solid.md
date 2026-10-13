---
id: kb-20261012-f27f
title: numpy 切片视图共享内存导致 cv2.addWeighted 半透明叠加恒为实心（bg_alpha 失效）
type: pitfall
domain:
- backend
tags:
- numpy-view
- opencv
- copy
- negative-index
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-23'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# numpy 切片视图共享内存导致 cv2.addWeighted 半透明叠加恒为实心（bg_alpha 失效）

## 背景 / 现象

**现象**：检测叠加框把目标整体盖成纯色矩形（如蓝框处只见实心蓝块、看不到车），无论 `bg_alpha`（透明度）配 0.3 还是 0.9 都一样, 半透明配置完全不起作用。

## 根因

**根因**（`app/engine/yolov/inference.py` 的 bg_alpha 半透明填充分支）：numpy 切片是**视图（共享内存）**而非副本：
```python
roi = out[y1:y2, x1:x2]                 # ← 视图, 与 out 同一块内存
cv2.rectangle(roi, ..., color, -1)      # 直接改脏了 out 本身(整块涂纯色)
out[y1:y2, x1:x2] = cv2.addWeighted(
    roi, alpha, out[y1:y2, x1:x2], 1-alpha, 0)   # roi 与 out[...] 是同一块纯色
```
`addWeighted` 两侧 `roi` 和 `out[y1:y2,x1:x2]` 指向**同一块已被涂成纯色的内存**，`α·纯色 + (1-α)·同一纯色 = 纯色`，与 α 无关 → 永远实心。

## 解决方案

**解决**：`roi = out[cy1:cy2, cx1:cx2].copy()` 断开共享内存，再在副本上画纯色矩形, `addWeighted` 才是真正的"副本(纯色) × 原图"混合：
```python
roi = out[cy1:cy2, cx1:cx2].copy()      # copy 断开视图
cv2.rectangle(roi, (0,0), (w-1,h-1), color, -1)
out[cy1:cy2, cx1:cx2] = cv2.addWeighted(roi, alpha, out[cy1:cy2, cx1:cx2], 1-alpha, 0)
```
配套两点：① alpha 封顶（`min(..., 0.5)`）——DB 默认 `bg_alpha=1.0`, 叠加框语义是"高亮目标"不是"遮盖", 服务端兜底保证目标始终可辨; ② bbox 先裁剪进画面（`max(0,x1)/min(fw,x2)`）——**越界负索引会被 numpy 当倒数索引**（`out[-10:…]` = 从倒数第 10 行开始）, 切片错位到画面另一角。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

**要点**：
- **对切片结果做"读-改-写回同源"运算（addWeighted/算术自加/np.copyto dst 同源）前必须 `.copy()`**——只要 `dst` 与某个输入是同一块内存, 就地写入会污染输入。
- cv2 画到切片视图 = 画到原图：想"只在局部画不影响原图再混合"就必须先 copy 出独立 buffer。
- numpy 负索引是"倒数"不是"越界钳制": 检测框 bbox 可能出界（x1<0 / x2>W）, 切片前务必 `clip` 进 `[0, W/H]`, 否则静默错位且不报错。
- 半透明/水印/ROI 混合类视觉后处理加一个**像素级单元断言**: 取混合区中心像素, 断言它介于"纯色"与"原图色"之间（`原色 < 混合 < 纯色`）, 恒实心会被立即抓住。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
