import React from 'react';
import { MessageSquarePlus, MessageSquare, LogOut, Loader2 } from 'lucide-react';
import { auth } from '../../config/firebase';
import { signOut } from 'firebase/auth';
import DocumentWidget from './DocumentWidget';

const Sidebar = ({ user, refreshTrigger, chatSessions, sessionsLoading, activeSessionId, onSelectSession, onNewChat }) => {
  const handleLogout = () => {
    signOut(auth);
  };

  return (
    <div className="sidebar glass-panel">
      <button className="new-chat-btn primary" onClick={onNewChat}>
        <MessageSquarePlus size={20} />
        <span>New Chat</span>
      </button>

      <div className="history-list">
        {sessionsLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '16px' }}>
            <Loader2 size={18} className="spin" />
          </div>
        ) : chatSessions.length === 0 ? (
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', padding: '8px 12px' }}>
            No past chats yet.
          </p>
        ) : (
          chatSessions.map((session) => (
            <div
              key={session.session_id}
              className={`history-item ${session.session_id === activeSessionId ? 'active' : ''}`}
              onClick={() => onSelectSession(session.session_id)}
              title={session.title}
            >
              <MessageSquare size={16} style={{ flexShrink: 0 }} />
              <span style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                flex: 1
              }}>
                {session.title}
              </span>
            </div>
          ))
        )}
      </div>

      <DocumentWidget refreshTrigger={refreshTrigger} />

      <div className="user-profile-block">
        <div className="user-info">
          <img
            src={user?.photoURL || 'https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y'}
            alt="Profile"
            className="profile-pic"
          />
          <div className="user-details">
            <span className="user-name">{user?.displayName || 'User'}</span>
            <span className="user-email">{user?.email}</span>
          </div>
        </div>
        <button className="logout-btn" onClick={handleLogout} title="Sign Out">
          <LogOut size={18} />
        </button>
      </div>
    </div>
  );
};

export default Sidebar;
