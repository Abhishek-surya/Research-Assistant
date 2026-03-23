import React from 'react';
import { signInWithPopup } from 'firebase/auth';
import { auth, googleProvider } from '../../config/firebase';
import { Sparkles, LogIn } from 'lucide-react';

const Login = () => {
  const handleGoogleSignIn = async () => {
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (error) {
      console.error("Error signing in with Google:", error);
      alert("Failed to sign in. Have you enabled Google Auth in the Firebase Console?");
    }
  };

  return (
    <div className="login-container">
      <div className="login-box glass-panel">
        <div className="login-header">
          <div className="logo-pulse">
            <Sparkles size={48} color="white" />
          </div>
          <h1>AI Research Assistant</h1>
          <p>Login to explore your documents and start chatting with your AI assistant.</p>
        </div>
        
        <button className="google-btn" onClick={handleGoogleSignIn}>
          <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google logo" className="google-icon" />
          <span>Sign in with Google</span>
          <LogIn size={20} className="login-icon" />
        </button>
      </div>
    </div>
  );
};

export default Login;
