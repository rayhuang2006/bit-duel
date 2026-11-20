# Bit Duel — 1024-bit Mathematical Arena

兩個 AI（例如 GPT 與 Claude）各以**單一最大 1024-bit 的程式**控制一個 `F_2^64` 線性動力系統。12 次策略修訂，每輪兩場交換攻守、每場 8 個初始條件、每個條件 64 個時間步。雙方只能見到少量公開回饋，程式與數學筆記於第十二輪後揭露。

> **這是可以執行的 v0.2 研究原型，不是已證明遊戲平衡的正式賽制。** `RULES.md` 為完整數學、計分與 VM 規則；`PROTOCOL.md` 為提交、密封和 GitHub 自動化規範。

## 先試試本機執行（不需 GitHub 帳號或 API key）

需求：Python 3.12+，`cryptography`。

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m bitduel.cli demo
python -m benchmarks.compare_baselines
python -m bitduel.cli assemble examples/local.asm --out /tmp/local.bin
```

`demo` 會使用兩份附帶的合法程式（52 bytes 的 `local.asm`、19 bytes 的 `sweep.asm`）跑完一輪，輸出雙方角色互換後的兩場分數。它**不是**真正的 GPT vs Claude 對戰，只是確定裁判、計分、組語和虛擬機可運作。

## 初始化 GitHub Repo

1. 用 `git init` 將這個資料夾推到自己新建的 GitHub repo，預設分支命名為 `main`，開啟 Issues 和 GitHub Actions。
2. 指定接收參賽留言的 Issue 已建立：[Issue #1](https://github.com/rayhuang2006/bit-duel/issues/1)。
3. 在本機執行：

```bash
python -m bitduel.cli init --game game-001 --user rayhuang2006 --issue 1
```

4. 這會建立：`config/game.json`（可公開）和 `.secrets/arena.env`（**不可提交**，已被 `.gitignore` 排除）。
5. 在 GitHub `Settings → Secrets and variables → Actions` 設定**唯一一個** Repository Secret：`ARENA_MASTER_SEED_HEX`。值在 `.secrets/arena.env` 裡；**絕不能把這個檔案提交到 Repo**。
6. 將 `config/game.json` 推上 GitHub。用 branch protection / ruleset 保護 `main` 上的 `bitduel/`、`.github/workflows/`、`config/` 等裁判關鍵檔案；盡量用專用 bot 授權，並限制誰能觸發提交。
7. 在 Issue #1 留下兩位 AI 的 **sealed submission**；完成雙方後 GitHub Actions 自動計分並推送 `results/game-001/round-01.json`。無需人工合併 PR。

> `init --user` 將同一 GitHub 帳號同時列為 GPT、Claude 的合法提交者，適合你擔任中繼者。若兩個 AI 有不同的 GitHub 身分，直接修改 `config/game.json` 的 `allowed_submitters`，分別列出相應 GitHub login。GitHub 身分本身**不能證明**留言文字由哪個模型生成。

## 為每個 AI 準備程式與備註

參賽者可以先寫 `strategy.asm`，使用附帶的 assembler 將它壓縮成機器碼：

```bash
python -m bitduel.cli assemble examples/local.asm --out /tmp/my_program.bin
```

接著準備數學研究筆記（範本 `examples/research_note.md`），然後加密成一則可以直接貼到 Issue #1 的留言：

```bash
python -m bitduel.cli submit \
  --round 1 --player gpt \
  --program /tmp/my_program.bin \
  --note examples/research_note.md \
  --out /tmp/gpt_round01_comment.txt
```

把 `/tmp/gpt_round01_comment.txt` **整份內容**貼到指定 Issue；它只包含一行標記與一行 base64 加密信封，不會洩漏原始程式。Claude 照相同流程提交，但使用 `--player claude`。也可透過 GitHub CLI：

```bash
gh issue comment 1 --body-file /tmp/gpt_round01_comment.txt
```

裁判在收到第二份合格的 sealed submission 時自動執行。結果只包含 score、每 8 步的平均 `q`、trial 0 的四筆 32-bit 公開觀測，以及承諾 hash；第 12 輪結束前不洩漏對方程式或研究筆記。每輪進度也會寫入 `results/game-001/leaderboard.json`。

**重要：每輪程式不是普通 PR 的明文檔案！** 若直接提交 `strategy.asm` 到公開 repo，對方可立即讀到，失去盲打意義。

## Repo 架構

```text
bit-duel/
├── RULES.md                  # 數學、評分、虛擬機規格
├── PROTOCOL.md               # GitHub 流程、加密、風險
├── bitduel/
│   ├── model.py              # 狀態演化/計分
│   ├── vm.py                 # 1024-bit 機器碼 VM
│   ├── asm.py                # assembler
│   ├── sealed.py             # 公開金鑰加密/承諾
│   ├── referee.py            # 收件、自動裁判、回饋/揭露
│   └── cli.py                # 命令列介面
├── examples/                 # 合法策略與筆記模板
├── tests/                    # 測試
├── .github/workflows/       # Issue 留言觸發裁判
├── config/game.json         # 初始化後產生 (public)
├── submissions/             # 加密收件紀錄
├── results/                 # 每輪有限回饋
├── reveal/                  # 第 12 輪自動揭露
└── .secrets/                # 永不提交 (本機私鑰/seed)
```

## 第 12 輪後：公開驗證

第 12 輪完結會產生 `reveal/game-001/all_rounds.json`，把它和完整 repo clone 到本機後執行：

```bash
python -m bitduel.cli verify
```

這個指令不需要裁判私鑰，會用公開 seed 重跑 12 輪，確認初始種子承諾、雙方程式承諾和每輪的完整計分數據都一致。

## 兩件不能忽略的事

**1. GitHub 自動裁判 ≠ ChatGPT/Claude 自動產生程式。** 這個 repo 已能收到兩份有效密封投稿時自動計分，但它不會自行喚醒兩個模型來寫新的策略。使用 ChatGPT/Claude 聊天訂閱的人可以手動帶結果去下一輪；要無人值守地生成 12 輪的模型策略，還需要額外整合可操作 GitHub 的代理或兩家模型的 API，且 API 計費與聊天訂閱通常分開。

**2. GitHub Actions 執行權限。** 此 repo 的 Issue 留言經解析、授權檢查和公鑰加密驗證後，**只在自製虛擬機中執行 128 bytes bytecode**，而不是 `eval` 不受信任的 Python 或 checkout PR 內提供的 script。要保護主分支、工作流程和裁判規則；擁有 repo 管理權限的人本質上是可信任裁判。請勿在有權限與 secrets 的工作流程 checkout 未經審核的 PR 程式。

## 進度與下一步

v0.2 已包含數學引擎、VM、assembler、公鑰密封、Issue intake、回合裁判、有限回饋、最終 reveal、GitHub Actions 與測試。尚未包含 AI API/agent 自動寫策略，亦未完成嚴格的平衡性研究；正式比賽前先用固定基準、未見初始條件及更多對手策略做驗證。

## 參賽模型提示詞

`examples/AI_INSTRUCTIONS.md` 是可以直接發給 GPT 與 Claude 的共用指令，特別明確要求「研究筆記、可驗證推導、預測與修正」，而不是只輸出下一份程式。兩方收到完全相同的規則；各自的提交會在第十二輪後公布。

## v0.2 規則修正

- `L=I+R+R^3`、`H=I+R` 與每步 4-bit 行動限制不變。
- 每一輪以 master seed + 輪次重新導出 8 組初始狀態；**同輪交換攻守使用相同的 8 組**。
- 每場總分最大 `8 × 64 × 64 = 32768`；0–100 配分的分母同步更新。
- GitHub 只需設定 **一個** `ARENA_MASTER_SEED_HEX` Secret，公鑰由同一種子導出。
- 非投稿的 Issue 留言不再執行裁判工作；Round 1 開始前仍需確定 Secret 已在 GitHub 設好。
- `BITDUEL_V1` 是密封封包協定版本，不需要因規則修改而改名字。
