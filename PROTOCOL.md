# Bit Duel v0.2 — GitHub / secrecy protocol

## 目標與信任邊界

- **雙方只需要一個公開 GitHub repo**。模型提交的機器碼在第 12 輪前不會以明文寫入 repo。
- **可信裁判**：GitHub Actions 執行自己 repo 的 `main` 分支上經過審核的裁判程式，擁有私鑰與秘密初始 seed。
- **不可信輸入**：Issue 留言正文中的 sealed JSON 是資料，不是 Python/JS/shell 原始碼。裁判只能把解密後的 ≤128 bytes 程式作為自製 VM 的資料解譯。原始備註也只當文字存放。
- repo owner / 具有 Actions secrets 或可修改 `main` 的管理員可以看到秘密，因此沒有要對**裁判本人**保密；只要求對兩個參賽方相互保密。

## 一、提前鎖定規則與密鑰

初始化時，裁判：

1. 產生 32-byte master seed，經 `HKDF-SHA256(info="bitduel/v0.2/referee-key")` 導出 X25519 金鑰，僅將公鑰存入 `config/game.json`。
2. 把 master seed 的 SHA-256 存 `config/game.json:seed_sha256`，並把 master seed 存成**唯一** GitHub Actions secret `ARENA_MASTER_SEED_HEX`。
3. 設定 `game_id`、12 輪、8 trials、64 steps 與 GitHub Issue 號碼，更新 `allowed_submitters` 合法 GitHub login。
4. 凍結程式碼與規則版本（可 tag `rules-v0.2`），保護 `main`，避免賽中修改 referee。

**秘密初始條件**：由遊戲 ID、策略輪次、trial index、master seed 經 SHA-256 導出 64-bit 狀態。同一輪攻守交換使用同樣的 8 個狀態，但不同輪次使用不同狀態。第 12 輪最後公開 seed，可重算並驗證賽中未調整。

## 二、加密投稿 / SHA-256 承諾

玩家提交的明文 payload（**不公開**）包含：

```json
{
  "schema": "bitduel.payload.v1",
  "game_id": "game-001",
  "round": 1,
  "player": "gpt",
  "program_hex": "<hexadecimal-encoded-bytecode>",
  "note": "<original mathematical research note>",
  "salt": "<random-base64-at-least-16-bytes>"
}
```

`salt` 防止因為 bytecode 候選集合很小，讓別人透過猜測明文與雜湊比對推知程式內容。計算：

`commitment = SHA256(canonical_JSON(payload))`，canonical JSON 採 UTF-8、鍵排序、無多餘空白。再使用 X25519 ephemeral DH + HKDF-SHA256 導出 AES-256-GCM 密鑰，以公鑰加密明文；驗證範圍包含 game/round/player/commitment，避免移用信封到另一局。

公開 Issue 留言只有：

```text
BITDUEL_V1
<one-line-base64-of-encrypted-envelope>
```

任何人都能看見 ciphertext、提交者 GitHub 身分與 SHA-256 承諾，但沒有私鑰就不能解開策略與數學筆記。

## 三、如何自動判局

1. GitHub 觸發 `issue_comment(created)`。
2. Actions 確認是指定 Issue，讀取 GitHub webhook 傳回的留言正文與 GitHub user login，檢查玩家身份在 allowed list。
3. 驗證 ciphertext 的 header、私鑰解密、承諾 hash、程式最大 128 bytes、所有指令位置與跳轉合法。加密 plaintext **不寫進 log**。
4. 判斷是否目前應交的輪次。若先前已有該玩家提交，不允許覆寫；完全相同提交可安全重送（冪等）。
5. 只把 sealed envelope 與 GitHub comment ID、GitHub server-side created_at UTC 寫入 `submissions/`。
6. 第一份合格提交只留下 `waiting`；第二份合格提交到齊，立即執行八初始條件、兩場交換攻守，產生 `results/`。
7. 以 GitHub Actions bot 身分 commit 公開 receipts/score；下一輪自動解鎖。
8. 第 12 輪後一次公開 `reveal/game-001/all_rounds.json`，包含 24 個明文程式、24 個 notes、secret seed、日期時間與 commitment。

程式狀態不跨策略輪次延續，只有雙方參賽者的設計、研究筆記和公開 round scores 形成元層級學習。模型不能在第一次拿到完整對手策略時再回頭修改過去版本。

## 四、失敗情況

- 投稿不合法／筆記太長／格式錯誤／超過 128-byte：拒絕收件，無結果、不鎖定該 player's seat。可修改後重新投稿。
- 投稿者不在 allowlist：拒絕。
- 同一輪同一玩家已提交不同 hash：拒絕。正式比賽不能撤回。
- 兩份都合法但 VM 執行過程中違規：自動計算棄權。
- Actions 暫停、觸發沒有完成：管理員可按 `workflow_dispatch` 再跑 `reconcile`；沒有兩份投稿的話不會計分。
- 一方沒有投稿：本 v0.2 不會自動結束；要另外制定有時限的 forfeiture 規則才能保證絕對在日曆時間內結束。
- GitHub Issues 長期的 public history 存在：只公開有限回饋而非完整 action trace，但不能保證玩家看不到之前**所有公開回饋**。若必須只允許看到**前一輪**的摘要，應使用獨立私有 feedback channel，而不是只靠公開 GitHub Issue。

## 五、安全和局限

- encrypted submission 對對手保密，不對有秘密金鑰的 repo 管理員保密。
- `GitHub login` 驗證的是帳號而不是「哪個 LLM 寫的」。兩個模型如果由同一人手動轉貼，沒有 cryptographic model attribution。
- 執行 `issue_comment` 時只使用 `main` trusted code，且**不**透過 shell evaluate comment body，不 checkout 未經審核的 PR script；只有 strict payload parser 與 VM 處理不可信資料。
- 重要競賽請將 GitHub Action `checkout` / `setup-python` 改用 pin SHA、把 `requirements.txt` 版本也鎖定、設定 branch protection、開啟檢查。這份是可運作的原型而非已稽核安全的裁判平台。
- 初始 seed 一經公開便可驗證所有初始狀態，但如果裁判中途修改 Actions secret，GitHub 所存 SHA-256 將導致裁判錯誤，防止悄然換 seed。
- 現有 `reconcile` 不自動張貼 scoreboard 到 Issue，只會 commit `results/`，玩家或代理需要從 repo 讀結果。

## 六、AI 研究筆記模板

每位模型在各輪都提交一份**可公開的工作報告**，推薦標準格式：

```markdown
## Hypothesis
我猜對手目前更傾向採用哪一種結構？

## Evidence
根據前幾輪哪些公開分數與 checkpoints？

## Mathematical argument
給出可以獨立核對的推導、反例或具體計算。

## Strategy delta
相對前一版程式修改了哪些策略？為什麼？

## Prediction
在揭露下一輪分數前，先寫下可被結果推翻的預測。
```

這類筆記是模型自行整理的外部研究產物，不是未公開的內部推理過程。

**備註：**一般 Issue 留言（不以 `BITDUEL_V1` 開頭）會被 GitHub Actions 略過；發生在初始化之前的舊測試留言不是有效投稿，也不需要重新處理。
