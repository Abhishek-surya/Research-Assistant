import React, { useState, useEffect } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from './config/firebase';
import './App.css';
import Sidebar from './components/layout/Sidebar';
import ChatArea from './components/chat/ChatArea';
import Login from './components/auth/Login';

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [messages, setMessages] = useState([
    {
      id: '1',
      sender: 'ai',
      text: 'Hello! I am your AI Research Assistant. How can I help you explore your documents today?'
    }
  ]);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setLoading(false);
    });

    return () => unsubscribe();
  }, []);

  const handleSendMessage = async (text) => {
    const userMsg = { id: Date.now().toString(), sender: 'user', text };
    setMessages(prev => [...prev, userMsg]);

    const loadingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: loadingId, sender: 'ai', text: 'Searching knowledge base...', isLoading: true }]);

    try {
      const token = await auth.currentUser.getIdToken();
      const response = await fetch('http://127.0.0.1:8000/api/chat', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: text })
      });

      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to fetch response');
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
      console.error("Chat error:", error);
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
      <Sidebar user={user} refreshTrigger={refreshTrigger} />
      <ChatArea messages={messages} onSendMessage={handleSendMessage} user={user} onDocumentAdded={() => setRefreshTrigger(p => p + 1)} />
    </div>
  );
}

export default App;
