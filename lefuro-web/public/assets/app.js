// 温泉資源庁 / Le Furo - フロントエンド最小スクリプト
(function () {
  "use strict";

  // フッターの年表示
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // 環境バッジ（http/https の別を表示）
  var badge = document.getElementById("env-badge");
  if (badge) {
    var secure = location.protocol === "https:";
    badge.textContent = secure
      ? "接続: HTTPS（SSL 有効）"
      : "接続: HTTP（SSL 未設定）";
  }

  // ヘルスチェック: /api/health.php を叩いて結果表示
  var btn = document.getElementById("health-btn");
  var out = document.getElementById("health-result");
  if (btn && out) {
    btn.addEventListener("click", function () {
      out.hidden = false;
      out.textContent = "確認中…";
      fetch("/api/health.php", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          out.textContent = JSON.stringify(data, null, 2);
        })
        .catch(function (err) {
          out.textContent = "エラー: " + err.message;
        });
    });
  }
})();
