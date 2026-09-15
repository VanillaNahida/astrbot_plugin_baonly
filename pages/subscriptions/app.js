const bridge = window.AstrBotPluginPage;

const $ = (sel) => document.querySelector(sel);

// ── 订阅列表 ──

async function loadList() {
  try {
    const data = await bridge.apiGet("subscriptions/list");
    const subs = data?.subscriptions ?? [];
    renderTable(subs);
    $("#count").textContent = String(subs.length);
    if (data?.storage_path) {
      $("#storage-path").textContent = "存储位置：" + data.storage_path;
    }
  } catch (error) {
    showToast("加载订阅列表失败：" + error.message, "error");
  }
}

function renderTable(subs) {
  const tbody = $("#sub-list");
  tbody.innerHTML = "";
  $("#empty").style.display = subs.length ? "none" : "block";

  for (const sub of subs) {
    const typeLabel = sub.is_group ? "群聊" : "私聊";
    const row = document.createElement("tr");

    const typeCell = document.createElement("td");
    typeCell.textContent = typeLabel;

    const idCell = document.createElement("td");
    idCell.textContent = sub.channel_id || "-";
    idCell.title = sub.umo;

    const displayCell = document.createElement("td");
    displayCell.textContent = sub.display || sub.channel_id || "-";

    const actionCell = document.createElement("td");
    const delBtn = document.createElement("button");
    delBtn.className = "btn danger";
    delBtn.textContent = "移除";
    delBtn.addEventListener("click", () => removeSub(sub.umo));
    actionCell.appendChild(delBtn);

    row.append(typeCell, idCell, displayCell, actionCell);
    tbody.appendChild(row);
  }
}

// ── 按号码添加 ──

function typeInfo() {
  return $("#type").value === "group"
    ? { is_group: true, label: "群聊" }
    : { is_group: false, label: "私聊" };
}

async function addByNumber() {
  const channel_id = $("#channel-id").value.trim();
  if (!channel_id) {
    showToast("请输入群号或 QQ 号", "error");
    return;
  }
  const info = typeInfo();
  try {
    const result = await bridge.apiPost("subscriptions/add", {
      is_group: info.is_group,
      channel_id,
    });
    showToast(result?.message || "添加成功", "success");
    $("#channel-id").value = "";
    await loadList();
  } catch (error) {
    showToast("添加失败：" + error.message, "error");
  }
}

// ── 群列表弹窗 ──

function openGroupsModal() {
  $("#groups-modal").hidden = false;
  loadGroupsIntoModal();
}

function closeGroupsModal() {
  $("#groups-modal").hidden = true;
  $("#group-select").innerHTML = "";
}

async function loadGroupsIntoModal() {
  const list = $("#group-select");
  const empty = $("#group-empty");
  list.innerHTML = "";
  empty.style.display = "block";
  empty.textContent = "正在加载群列表，请稍候……";
  try {
    const [groupData, subData] = await Promise.all([
      bridge.apiGet("subscriptions/groups"),
      bridge.apiGet("subscriptions/list"),
    ]);
    const groups = groupData?.groups ?? [];
    const subs = subData?.subscriptions ?? [];
    // 已订阅的群 id 集合，用于弹窗内自动勾选/禁用，避免重复添加
    const subscribedIds = new Set(
      subs
        .filter((s) => s.is_group)
        .map((s) => String(s.channel_id || ""))
        .filter(Boolean)
    );
    renderGroupSelect(groups, subscribedIds);
    if (!groups || groups.length === 0) {
      empty.textContent = "未获取到群列表（请确认平台支持并已连接）。";
      empty.style.display = "block";
    }
  } catch (error) {
    empty.textContent = "加载群列表失败：" + error.message;
    empty.style.display = "block";
  }
}

function renderGroupSelect(groups, subscribedIds) {
  const list = $("#group-select");
  const empty = $("#group-empty");
  list.innerHTML = "";
  empty.style.display = "none";

  for (const g of groups) {
    const gid = String(g.group_id || "");
    const alreadySubscribed = gid && subscribedIds.has(gid);

    const li = document.createElement("li");
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = g.group_id;
    checkbox.dataset.name = g.group_name || "";
    if (alreadySubscribed) {
      checkbox.checked = true;
      checkbox.disabled = true; // 已订阅的群不可重复勾选
    }
    label.appendChild(checkbox);
    label.appendChild(
      document.createTextNode(
        ` ${g.group_name || "未知群"}（${g.group_id}）${alreadySubscribed ? "（已订阅）" : ""}`
      )
    );
    li.appendChild(label);
    list.appendChild(li);
  }
}

async function confirmGroups() {
  const checked = [
    ...document.querySelectorAll("#group-select input[type=checkbox]:checked"),
  ];
  if (checked.length === 0) {
    showToast("请至少选择一个群", "error");
    return;
  }
  let ok = 0;
  let failed = 0;
  for (const cb of checked) {
    try {
      const result = await bridge.apiPost("subscriptions/add", {
        is_group: true,
        channel_id: cb.value,
      });
      ok += 1;
    } catch (error) {
      failed += 1;
    }
  }
  if (failed === 0) {
    showToast(`已成功订阅 ${ok} 个群`, "success");
  } else {
    showToast(`成功 ${ok} 个，失败 ${failed} 个`, "error");
  }
  closeGroupsModal();
  await loadList();
}

// ── 移除 ──

async function removeSub(umo) {
  // 插件 Page 的受限 iframe 不支持原生 confirm()，改为直接操作并用页内 toast 反馈
  try {
    showToast("正在移除订阅……", "info");
    const result = await bridge.apiPost("subscriptions/remove", { umo });
    showToast(result?.message || "已移除", "success");
    await loadList();
  } catch (error) {
    showToast("移除失败：" + error.message, "error");
  }
}

// ── 右上角 Toast ──

let toastTimer = null;
function showToast(text, kind = "info") {
  const toast = $("#toast");
  toast.textContent = text;
  // 复用 data-kind 便于配色，也直接切换 class
  toast.className = "toast show " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 3000);
}

// ── 初始化 ──

async function init() {
  await bridge.ready();
  document.title = "订阅管理 - BAOnly";
  $("#build-umo").addEventListener("click", addByNumber);
  $("#open-groups").addEventListener("click", openGroupsModal);
  $("#close-groups").addEventListener("click", closeGroupsModal);
  $("#confirm-groups").addEventListener("click", confirmGroups);
  $("#refresh-list").addEventListener("click", async () => {
    showToast("正在刷新订阅列表……", "info");
    await loadList();
  });
  await loadList();
}

init();
