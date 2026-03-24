import React, { useState, useEffect, useCallback } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from './config/firebase';
import { API_BASE_URL } from './config/api';
import './App.css';
import Sidebar from './components/layout/Sidebar';
import ChatArea from './components/chat/ChatArea';
import Login from './components/auth/Login';

const WELCOME_MSG = {
  id: 'welcome',
  sender: 'ai',
  text: 'Hello! I am your AI Research Assistant. How can I help you explore your documents today?'
};

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Chat state
  const [messages, setMessages] = useState([WELCOME_MSG]);
  const [activeSessionId, setActiveSessionId] = useState(null);

  // Sidebar history
  const [chatSessions, setChatSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  // Fetch the list of past sessions whenever the user logs in
  const fetchSessions = useCallback(async () => {
    if (!auth.currentUser) return;
    setSessionsLoading(true);
    try {
      const token = await auth.currentUser.getIdToken();
      const res = await fetch(`${API_BASE_URL}/chats`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to fetch sessions');
      const data = await res.json();
      setChatSessions(data.sessions || []);
    } catch (err) {
      console.error('Failed to load chat sessions:', err);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) fetchSessions();
  }, [user, fetchSessions]);

  // Load messages for an old session when user clicks sidebar item
  const handleSelectSession = async (sessionId) => {
    if (sessionId === activeSessionId) return;
    try {
      const token = await auth.currentUser.getIdToken();
      const res = await fetch(`${API_BASE_URL}/chats/${sessionId}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to load session');
      const data = await res.json();

      // Reconstruct messages array from Q&A turns
      const loaded = [];
      data.messages.forEach((turn, idx) => {
        loaded.push({ id: `${sessionId}-q-${idx}`, sender: 'user', text: turn.query });
        loaded.push({ id: `${sessionId}-a-${idx}`, sender: 'ai', text: turn.reply });
      });

      setMessages(loaded.length > 0 ? loaded : [WELCOME_MSG]);
      setActiveSessionId(sessionId);
    } catch (err) {
      console.error('Failed to load session messages:', err);
    }
  };

  // Start a brand new chat
  const handleNewChat = () => {
    setMessages([WELCOME_MSG]);
    setActiveSessionId(null);
  };

  const handleSendMessage = async (text, attachment = null) => {
    let apiMessage = text;
    if (attachment && attachment.text) {
      const snippet = attachment.text.length > 500 ? attachment.text.substring(0, 500) + '...' : attachment.text;
      const label = attachment.type === 'link' ? `Web Page: ${attachment.name}` : `Document: ${attachment.name}`;
      apiMessage = text ? `${text}\n\n[${label}]\n${snippet}` : `[${label}]\n${snippet}`;
    }

    const userMsg = {
      id: Date.now().toString(),
      sender: 'user',
      text: text || '',
      attachment: attachment ? { name: attachment.name, type: attachment.type } : null
    };

    setMessages(prev => [...prev, userMsg]);

    const loadingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: loadingId, sender: 'ai', text: 'Searching knowledge base...', isLoading: true }]);

    try {
      const token = await auth.currentUser.getIdToken();
      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: apiMessage, session_id: activeSessionId })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to fetch response');
      }

      // Persist the session_id returned by the backend
      if (data.session_id && !activeSessionId) {
        setActiveSessionId(data.session_id);
        // Refresh sidebar to include the new session
        fetchSessions();
      }

      setMessages(prev => prev.map(msg =>
        msg.id === loadingId
          ? {
              id: loadingId,
              sender: 'ai',
              text: data.reply,
              contextChunks: data.context_chunks || []
            }
          : msg
      ));
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => prev.map(msg =>
        msg.id === loadingId
          ? { id: loadingId, sender: 'ai', text: `Error: ${error.message}` }
          : msg
      ));
    }
  };

  if (loading) {
    return <div className="app-container" style={{ alignItems: 'center', justifyContent: 'center' }}>Loading...</div>;
  }

  if (!user) {
    return <Login />;
  }

  return (
    <div className="app-container">
      <Sidebar
        user={user}
        refreshTrigger={refreshTrigger}
        chatSessions={chatSessions}
        sessionsLoading={sessionsLoading}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
      />
      <ChatArea
        messages={messages}
        onSendMessage={handleSendMessage}
        user={user}
        onDocumentAdded={() => setRefreshTrigger(p => p + 1)}
      />
    </div>
  );
}

export default App;
