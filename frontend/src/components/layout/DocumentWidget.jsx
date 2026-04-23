import React, { useState, useEffect } from 'react';
import { auth } from '../../config/firebase';
import { API_BASE_URL } from '../../config/api';
import { FileText, Globe, Loader2, Trash2, RefreshCw } from 'lucide-react';

const DocumentWidget = ({ refreshTrigger }) => {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deletingFile, setDeletingFile] = useState(null);

  const fetchDocuments = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const token = await auth.currentUser?.getIdToken();
      if (token) {
        const response = await fetch(`${API_BASE_URL}/documents`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) {
          const data = await response.json();
          setDocuments(data.documents || []);
        }
      }
    } catch (err) {
      console.error('Failed to fetch documents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (auth.currentUser) fetchDocuments();
  }, [refreshTrigger]);

  // Restart auto-polling ONLY if there are processing documents to save Read quota
  useEffect(() => {
    let interval;
    const hasProcessing = documents.some(doc => doc.status === 'processing');
    
    if (hasProcessing) {
      interval = setInterval(() => {
        fetchDocuments(true); // silent refresh
      }, 30000); // 30 second safety interval
    }
    
    return () => {
      if (interval) clearInterval(interval);
    };
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

  // Filter out metadata files like .summary.md, maintaining only actual PDFs and web links
  const validDocuments = documents.filter(d => {
    if (d.type === 'web') return true;
    return d.filename && d.filename.toLowerCase().endsWith('.pdf');
  });

  const pdfDocs = validDocuments.filter(d => d.type !== 'web');
  const webDocs = validDocuments.filter(d => d.type === 'web');

  const renderDocList = (docs) => (
    <div className="document-list" style={{ marginBottom: '0.75rem' }}>
      {docs.map((doc, idx) => (
        <div key={idx} className="document-item">
          {doc.type === 'web' ? <Globe size={15} className="doc-icon" /> : <FileText size={15} className="doc-icon" />}
          <span className="doc-name" title={doc.name}>{doc.name}</span>
          
          {doc.status === 'processing' && (
            <span className="processing-badge" title="Embedding chunks in background...">
              <Loader2 size={12} className="spin" />
            </span>
          )}
          {doc.status === 'error' && (
            <span className="error-badge" title="Vector embedding failed (API Limit Exceeded or Error). Please delete and try again." style={{ color: '#ef4444', marginLeft: 'auto', marginRight: '8px' }}>
              ⚠️
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
  );

  return (
    <div className="document-widget">
      <div className="widget-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <h3 className="widget-title" style={{ margin: 0 }}>Knowledge Base</h3>
        <button 
          onClick={() => fetchDocuments()} 
          disabled={loading}
          className="refresh-btn"
          title="Manual Refresh"
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px' }}
        >
          <RefreshCw size={14} className={loading ? 'spin' : ''} />
        </button>
      </div>
      {loading ? (
        <div className="loader-center" style={{ display: 'flex', justifyContent: 'center', padding: '1rem' }}><Loader2 className="spin" size={16} /></div>
      ) : documents.length === 0 ? (
        <p className="empty-text" style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No documents yet.</p>
      ) : (
        <div style={{ overflowY: 'auto', flexGrow: 1 }}>
          {pdfDocs.length > 0 && (
            <>
              <h4 style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem', marginTop: '0.5rem', fontWeight: 500 }}>Uploaded Documents</h4>
              {renderDocList(pdfDocs)}
            </>
          )}
          {webDocs.length > 0 && (
            <>
              <h4 style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem', marginTop: '0.5rem', fontWeight: 500 }}>Scraped URLs</h4>
              {renderDocList(webDocs)}
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default DocumentWidget;
