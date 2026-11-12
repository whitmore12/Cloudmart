/* ===== messaging.js — shared by index.html and profile.html =====
   Matches the Flask routes in app.py:
     POST /api/messages              {sender_id, receiver_id, listing_id, body}
     GET  /api/messages/chats        ?user_id=
     GET  /api/messages/chat         ?user_id=&other_user_id=&listing_id=
     PUT  /api/messages/read         {user_id, other_user_id, listing_id}
   A "chat" = one listing + one other person. */

let msgListingId = null;
let msgReceiverId = null;
let activeChat = null; // { listingId, otherUserId }

function msgUser() { return JSON.parse(localStorage.getItem("user") || "null"); }
function msgEsc(v) {
  return String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
async function msgFetch(path, options) {
  const res = await fetch(window.location.origin + path, options);
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error((data && data.error) || "Request failed.");
  return data;
}
function msgPost(path, method, payload) {
  return msgFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/* ---------- index.html: message seller popup ---------- */
function openMessageBox(listingId) {
  const me = msgUser();
  if (!me) return alert("Please log in first.");
  const item = (typeof allListings !== "undefined" ? allListings : [])
    .find(i => Number(i.id) === Number(listingId));
  if (!item) return alert("Could not find that listing.");

  msgListingId = Number(item.id);
  msgReceiverId = Number(item.user_id); // the seller
  document.getElementById("msgItemTitle").textContent = `Message about: ${item.title}`;
  document.getElementById("msgSellerName").textContent = item.seller ? `To: ${item.seller}` : "";
  document.getElementById("msgBody").value = "";
  setMsgStatus("");
  document.getElementById("msgOverlay").classList.add("open");
  document.getElementById("msgBody").focus();
}

function closeMessageBox() {
  document.getElementById("msgOverlay").classList.remove("open");
  msgListingId = null;
  msgReceiverId = null;
}

function setMsgStatus(text, type) {
  let el = document.getElementById("msgStatus");
  if (!el) {
    el = document.createElement("p");
    el.id = "msgStatus";
    document.querySelector(".msg-box .msg-actions").before(el);
  }
  el.className = "msg-status " + (type || "");
  el.textContent = text;
}

async function sendMessageToSeller() {
  const me = msgUser();
  const body = document.getElementById("msgBody").value.trim();
  if (!body) return setMsgStatus("Please write a message first.", "error");
  const btn = document.getElementById("msgSendBtn");
  btn.disabled = true;
  try {
    await msgPost("/api/messages", "POST", {
      sender_id: me.id,
      receiver_id: msgReceiverId,
      listing_id: msgListingId,
      body,
    });
    setMsgStatus("Message sent! Find replies under Messages on your profile.", "ok");
    setTimeout(closeMessageBox, 1200);
  } catch (err) {
    setMsgStatus(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

/* ---------- profile.html: inbox + chat ---------- */
async function initMessaging() {
  const me = msgUser();
  if (!me) return;
  if (typeof isViewingOwnProfile === "function" && !isViewingOwnProfile()) return;
  document.getElementById("messagesNavBtn").style.display = "inline-block";
  document.getElementById("messagesSection").style.display = "block";
  await loadChats();
}

async function loadChats() {
  const me = msgUser();
  const list = document.getElementById("chatList");
  const empty = document.getElementById("chatsEmpty");
  try {
    const chats = await msgFetch(`/api/messages/chats?user_id=${encodeURIComponent(me.id)}`);
    list.innerHTML = "";
    empty.style.display = chats.length ? "none" : "block";
    chats.forEach(c => {
      const div = document.createElement("div");
      div.className = "chat-item";
      const unread = c.unread_count > 0 ? `<span class="chat-unread">${c.unread_count}</span>` : "";
      div.innerHTML = `<strong>${msgEsc(c.other_username)} ${unread}</strong>
        <span class="muted">${msgEsc(c.listing_title)}</span>
        <div class="chat-preview">${c.last_message_from_me ? "You: " : ""}${msgEsc(c.last_message)}</div>`;
      div.onclick = () => openChat(c.listing_id, c.other_user_id);
      list.appendChild(div);
    });
  } catch (err) {
    list.innerHTML = `<p class="empty">${msgEsc(err.message)}</p>`;
  }
}

async function openChat(listingId, otherUserId) {
  activeChat = { listingId, otherUserId };
  document.getElementById("chatPanel").style.display = "block";
  await refreshChat();
  // Mark messages sent to me as read, then update the unread badges
  try {
    await msgPost("/api/messages/read", "PUT", {
      user_id: msgUser().id, other_user_id: otherUserId, listing_id: listingId,
    });
    loadChats();
  } catch (e) { console.error(e); }
}

async function refreshChat() {
  if (!activeChat) return;
  const me = msgUser();
  const box = document.getElementById("chatMessages");
  const q = `user_id=${encodeURIComponent(me.id)}&other_user_id=${activeChat.otherUserId}&listing_id=${activeChat.listingId}`;
  try {
    const data = await msgFetch(`/api/messages/chat?${q}`);
    document.getElementById("chatTitle").textContent = data.listing.title;
    document.getElementById("chatWith").textContent = `With ${data.other_user.username}`;
    box.innerHTML = data.messages.map(m => {
      const mine = Number(m.sender_id) === Number(me.id);
      const when = m.created_at ? new Date(m.created_at.replace(" ", "T")).toLocaleString() : "";
      return `<div class="chat-bubble ${mine ? "mine" : ""}">${msgEsc(m.body)}<small>${msgEsc(when)}</small></div>`;
    }).join("") || `<p class="empty">No messages yet.</p>`;
    box.scrollTop = box.scrollHeight;
  } catch (err) {
    box.innerHTML = `<p class="empty">${msgEsc(err.message)}</p>`;
  }
}

function closeChat() {
  activeChat = null;
  document.getElementById("chatPanel").style.display = "none";
}

async function sendChatReply() {
  if (!activeChat) return;
  const input = document.getElementById("chatReplyInput");
  const body = input.value.trim();
  if (!body) return;
  try {
    await msgPost("/api/messages", "POST", {
      sender_id: msgUser().id,
      receiver_id: activeChat.otherUserId,
      listing_id: activeChat.listingId,
      body,
    });
    input.value = "";
    await refreshChat();
    loadChats();
  } catch (err) {
    alert(err.message);
  }
}
