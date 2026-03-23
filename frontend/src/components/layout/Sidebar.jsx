import React from 'react';
import { MessageSquarePlus, MessageSquare, LogOut } from 'lucide-react';
import { auth } from '../../config/firebase';
import { signOut } from 'firebase/auth';
import DocumentWidget from './DocumentWidget';

const Sidebar = ({ user, refreshTrigger }) => {
  const handleLogout = () => {
    signOut(auth);
  };

  return (
    <div className="sidebar glass-panel">
      <button className="new-chat-btn primary">
        <MessageSquarePlus size={20} />
        <span>New Chat</span>
      </button>

      <div className="history-list">
        <div className="history-item active">
          <MessageSquare size={18} />
          <span>Firebase Setup</span>
        </div>
        <div className="history-item">
          <MessageSquare size={18} />
          <span>React Concepts</span>
        </div>
        <div className="history-item">
          <MessageSquare size={18} />
          <span>System Architecture</span>
        </div>
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
