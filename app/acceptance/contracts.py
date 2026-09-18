"""Versioned capabilities. A catalog entry is not an implemented agent."""

CONTRACT_VERSION = "acceptance-2026-09-18.1"
CATALOG = [
    {
        "id": "collection",
        "name": "資料收集",
        "implemented": True,
        "scope": "檔案解析、期間核對、來源定位；不代表事實已核驗",
        "capabilities": ["內容完整且可定位", "工作期間與提交日期分離", "格式、版本與衝突檢查"],
        "specs": [
            "提交日期在下一週仍讀取正文工作期間",
            "公式不當成已計算數值",
            "必要資料漏失不得回報成功",
        ],
    },
    {
        "id": "identity",
        "name": "身份歸檔",
        "implemented": False,
        "scope": "待實作；只能查看能力契約",
        "capabilities": ["別名歸一", "同名區分", "公司與暫代生效期間"],
        "specs": ["同別名同員工合併", "兩家公司同名員工不可合併", "接任前成果不得歸給接任者"],
    },
    {
        "id": "deduplication",
        "name": "項目去重",
        "implemented": False,
        "scope": "待實作",
        "capabilities": ["跨週跨月项目連續性", "區分新增交付與重述"],
        "specs": ["同項目改名仍延續", "相似名稱不同交付不得合併", "上月成果不得再次計功"],
    },
    {
        "id": "contribution",
        "name": "貢獻核驗",
        "implemented": False,
        "scope": "待實作",
        "capabilities": ["主責、實作、協作區分", "交付與驗收佐證"],
        "specs": ["團隊產出不得全歸效能官", "人工評語不是已證實事實", "缺驗收記錄須標示未核驗"],
    },
    {
        "id": "capability",
        "name": "能力邊界",
        "implemented": False,
        "scope": "待實作",
        "capabilities": ["單次成功、協助與獨立穩定能力區分"],
        "specs": ["單次成功不能判定穩定能力", "多次獨立交付需保留證據", "他人協助不可省略"],
    },
    {
        "id": "potential",
        "name": "潛力信號",
        "implemented": False,
        "scope": "待實作",
        "capabilities": ["多次學習與遷移事件", "表達不確定性"],
        "specs": ["一次成功不可判高潛", "無學習記錄須保留未知", "學習速度須有起點與掌握證據"],
    },
    {
        "id": "review",
        "name": "獨立審核",
        "implemented": False,
        "scope": "待實作",
        "capabilities": ["矛盾檢查", "證據不足", "規則違反"],
        "specs": ["找出植入的錯人結論", "找出無來源數字", "不得原樣同意上游結果"],
    },
    {
        "id": "report",
        "name": "報告生成",
        "implemented": False,
        "scope": "待實作",
        "capabilities": ["3–5 個重點", "效能中心貢獻", "P0 與來源忠實性"],
        "specs": ["不編造數字", "分開業務成果與中心推動", "保留未決風險與優先級"],
    },
    {
        "id": "supervisor",
        "name": "總管收件流程",
        "implemented": True,
        "scope": "僅收件切片：歸檔、版本、重試；完整多 Agent 依賴編排尚未實作",
        "capabilities": ["正確路由與等待確認", "版本與冪等", "失敗恢復"],
        "specs": ["未驗證不可放行", "重試不重複歸檔", "耗盡重試必須失敗而非完成"],
    },
]


def contract(agent):
    return next((row for row in CATALOG if row["id"] == agent), None)
