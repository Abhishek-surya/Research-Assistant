import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, Paperclip, Loader2, FileText, Link as LinkIcon, X, Globe, Info } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { auth } from '../../config/firebase';
import { API_BASE_URL } from '../../config/api';

const ChatArea = ({ messages, onSendMessage, user, onDocumentAdded }) => {
  const [input, setInput] = useState('');
  const [attachment, setAttachment] = useState(null);
  const [showUrlInput, setShowUrlInput] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [activeDebugId, setActiveDebugId] = useState(null);

  const endOfMessagesRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = '';
    setIsUploading(true);
    setUploadStatus('Extracting document text...');
    try {
      const token = await auth.currentUser.getIdToken();
      const formData = new FormData();
      formData.append('document', file);
      const response = await fetch(`${API_BASE_URL}/upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed');
      setAttachment({ name: file.name, text: data.text, type: 'file' });
      
      // Signal sidebar to refresh the documents list
      if (onDocumentAdded) onDocumentAdded();
    } catch (error) {
      alert('Upload failed: ' + error.message);
    } finally {
      setIsUploading(false);
      setUploadStatus('');
    }
  };

  const handleAddUrl = async (e) => {
    e.preventDefault();
    if (!urlInput.trim()) return;
    
    setShowUrlInput(false);
    setIsUploading(true);
    setUploadStatus('Scraping web page...');
    
    try {
      const token = await auth.currentUser.getIdToken();
      const response = await fetch(`${API_BASE_URL}/scrape`, {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json' 
        },
        body: JSON.stringify({ url: urlInput.trim() })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Scraping failed');
      
      setAttachment({ name: data.title || urlInput, text: data.text, url: data.url, type: 'link' });
      setUrlInput('');
      
      // Signal sidebar to refresh the documents list
      if (onDocumentAdded) onDocumentAdded();
    } catch (error) {
      alert('Scraping failed: ' + error.message);
    } finally {
      setIsUploading(false);
      setUploadStatus('');
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() || attachment) {
      onSendMessage(input.trim(), attachment);
      setInput('');
      setAttachment(null);
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="chat-container">
      <div className="chat-inner">
        <div className="chat-header">
          <h1>AI Research Assistant</h1>
        </div>

        <div className="messages-area">
          {messages.map((msg) => (
            <div key={msg.id} className={`message ${msg.sender}`}>
              <div className={`avatar ${msg.sender}`}>
                {msg.sender === 'user' ? (
                  <img src={user?.photoURL || ''} alt="User" style={{ width: '100%', height: '100%', borderRadius: '50%' }} />
                ) : (
                  <Sparkles size={20} color="#ececec" />
                )}
              </div>
              <div className="message-content">
                {msg.sender === 'ai' && !msg.isLoading ? (
                  <div className="markdown-prose">
                    <ReactMarkdown>{msg.text}</ReactMarkdown>
                  </div>
                ) : msg.sender === 'user' ? (
                  <div className="user-message-content" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {msg.attachment && (
                      <div className="message-attachment-badge" style={{ 
                        display: 'inline-flex', 
                        alignItems: 'center', 
                        gap: '6px', 
                        backgroundColor: 'rgba(255, 255, 255, 0.15)', 
                        padding: '6px 10px', 
                        borderRadius: '6px', 
                        fontSize: '13px',
                        fontWeight: '500',
                        width: 'fit-content'
                      }}>
                        {msg.attachment.type === 'link' ? <Globe size={14} /> : <FileText size={14} />}
                        <span>{msg.attachment.name}</span>
                      </div>
                    )}
                    {msg.text && <div>{msg.text}</div>}
                  </div>
                ) : (
                  msg.text
                )}
                {msg.isLoading && <span className="typing-indicator"><span>.</span><span>.</span><span>.</span></span>}
                
                {/* Debug UI for Context Chunks */}
                {msg.contextChunks && msg.contextChunks.length > 0 && (
                  <div className="debug-container">
                    <button 
                      className="info-btn"
                      onClick={() => setActiveDebugId(activeDebugId === msg.id ? null : msg.id)}
                      title="View Retrieved Context"
                    >
                      <Info size={14} />
                      <span>Sources ({msg.contextChunks.length})</span>
                    </button>
                    
                    {activeDebugId === msg.id && (
                      <div className="debug-panel glass-panel">
                        <div className="debug-header">
                          <h4>Retrieved Context Chunks</h4>
                          <button onClick={() => setActiveDebugId(null)}><X size={14} /></button>
                        </div>
                        <div className="chunks-list">
                          {msg.contextChunks.map((chunk, idx) => (
                            <div key={idx} className="chunk-card">
                              <div className="chunk-meta">
                                <span className="chunk-source">
                                  {chunk.doc_type === 'web' ? <Globe size={12}/> : <FileText size={12}/>}
                                  {chunk.document_name}
                                </span>
                                <span className="chunk-score">Score: {chunk.score.toFixed(3)}</span>
                              </div>
                              <p className="chunk-text">"{chunk.text}"</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={endOfMessagesRef} />
        </div>

        <div className="input-container">
          {attachment && (
            <div className="attachment-preview">
              {attachment.type === 'link' ? <Globe size={16} /> : <FileText size={16} />}
              <span>{attachment.name}</span>
              <button type="button" onClick={() => setAttachment(null)}>✕</button>
            </div>
          )}

          {showUrlInput && (
            <div className="url-input-popover glass-panel">
              <input 
                 type="text" 
                 placeholder="Paste web URL to scrape..." 
                 value={urlInput} 
                 onChange={(e) => setUrlInput(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') handleAddUrl(e); }}
                 autoFocus
              />
              <button type="button" onClick={handleAddUrl} className="primary-sm">Scrape</button>
              <button type="button" onClick={() => setShowUrlInput(false)} className="close-sm"><X size={16}/></button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="input-box glass-panel">
            <input 
              type="file" 
              ref={fileInputRef} 
              onChange={handleFileUpload}
              accept=".pdf,.txt"
              style={{ display: 'none' }} 
            />
            <div className="attach-actions">
              <button 
                type="button" 
                className="attach-btn" 
                onClick={() => fileInputRef.current.click()}
                disabled={isUploading || attachment != null}
                title="Upload PDF or TXT"
              >
                {isUploading && uploadStatus.includes('Extracting') ? <Loader2 size={20} className="spin" /> : <Paperclip size={20} />}
              </button>
              <button 
                type="button" 
                className="attach-btn" 
                onClick={() => setShowUrlInput(!showUrlInput)}
                disabled={isUploading || attachment != null}
                title="Scrape Web URL"
              >
                {isUploading && uploadStatus.includes('Scraping') ? <Loader2 size={20} className="spin" /> : <LinkIcon size={20} />}
              </button>
            </div>

            <textarea
              ref={textareaRef}
              className="chat-input"
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${e.target.scrollHeight}px`;
              }}
              onKeyDown={handleKeyDown}
              placeholder={isUploading ? uploadStatus : "Message AI Research Assistant..."}
              rows={1}
              disabled={isUploading}
            />
            <button 
              type="submit" 
              className="send-btn"
              disabled={(!input.trim() && !attachment) || isUploading}
            >
              <Send size={18} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default ChatArea;
