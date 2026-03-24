import React, { useState, useEffect } from 'react';
import { auth } from '../../config/firebase';
import { API_BASE_URL } from '../../config/api';
import { FileText, Globe, Loader2, Trash2 } from 'lucide-react';

const DocumentWidget = ({ refreshTrigger }) => {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deletingFile, setDeletingFile] = useState(null);

  const fetchDocuments = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const token = await auth.currentUser?.getIdToken();
      if (!token) return;
      const response = await fetch(`${API_BASE_URL}/documents`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      setDocuments(data.documents || []);
    } catch (err) {
      setDocuments([]);
      console.error('Failed to fetch documents:', err);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    if (auth.currentUser) fetchDocuments();
  }, [refreshTrigger]);

  // Auto-poll every 10 seconds if any documents are still processing
  useEffect(() => {
    let interval;
    const isProcessing = documents.some(d => d.status === 'processing');
    if (isProcessing) {
      interval = setInterval(() => {
        fetchDocuments(true); // silent refresh
      }, 10000);
    }
    return () => clearInterval(interval);
  }, [documents]);

  const handleDelete = async (filename) => {
    if (!window.confirm(`Delete "${filename}" and all its chunks?`)) return;
    setDeletingFile(filename);
    try {
      const token = await auth.currentUser?.getIdToken();
      const response = await fetch(`${API_BASE_URL}/documents/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Delete failed');
      // Refresh list after deletion
      await fetchDocuments();
    } catch (err) {
      alert('Delete failed: ' + err.message);
    } finally {
      setDeletingFile(null);
    }
  };

  return (
    <div className="document-widget">
      <h3 className="widget-title">Knowledge Base</h3>
      {loading ? (
        <div className="loader-center"><Loader2 className="spin" size={16} /></div>
      ) : documents.length === 0 ? (
        <p className="empty-text" style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No documents yet.</p>
      ) : (
        <div className="document-list">
          {documents.map((doc, idx) => (
            <div key={idx} className="document-item">
              {doc.type === 'web' ? <Globe size={15} className="doc-icon" /> : <FileText size={15} className="doc-icon" />}
              <span className="doc-name" title={doc.name}>{doc.name}</span>
              
              {doc.status === 'processing' && (
                <span className="processing-badge" title="Embedding chunks in background...">
                  <Loader2 size={12} className="spin" />
                </span>
              )}
              <button
                className="doc-delete-btn"
                title="Delete document and all its chunks"
                onClick={() => handleDelete(doc.filename)}
                disabled={deletingFile === doc.filename}
              >
                {deletingFile === doc.filename
                  ? <Loader2 size={13} className="spin" />
                  : <Trash2 size={13} />}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default DocumentWidget;
