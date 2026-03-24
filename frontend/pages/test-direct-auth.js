import { useState } from 'react';

export default function TestDirectAuth() {
  const [result, setResult] = useState('');
  const [cookies, setCookies] = useState('');
  const [apiResult, setApiResult] = useState('');

  const testAPI = async () => {
    try {
      console.log('Testing API call...');
      const response = await fetch('/api/v1/sessions?limit=5', {
        credentials: 'include',
        headers: {
          'Accept': 'application/json'
        }
      });
      
      console.log('API response status:', response.status);
      console.log('API response headers:', Object.fromEntries(response.headers.entries()));
      
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API request failed: ${response.status} - ${errorText}`);
      }
      
      const data = await response.json();
      console.log('API result:', data);
      setApiResult(JSON.stringify(data, null, 2));
    } catch (error) {
      console.error('API Error:', error);
      setApiResult('API Error: ' + error.message);
    }
  };

  const testDirectLogin = async () => {
    try {
      // First, let's check current cookies and session
      console.log('Current cookies:', document.cookie);
      
      // Test current session
      console.log('Testing current session...');
      const sessionResponse = await fetch('/auth/sessions/whoami', {
        credentials: 'include',
        headers: {
          'Accept': 'application/json'
        }
      });
      
      console.log('Session response status:', sessionResponse.status);
      
      if (sessionResponse.ok) {
        const sessionData = await sessionResponse.json();
        console.log('Current session:', sessionData);
        setResult('Already logged in!\n' + JSON.stringify(sessionData, null, 2));
        setCookies(document.cookie);
        return;
      }
      
      // If no session, try to login
      console.log('No current session, proceeding with login...');
      
      // 1. Get login flow through Next.js proxy
      console.log('Step 1: Getting login flow...');
      const flowResponse = await fetch('/auth/self-service/login/browser?refresh=true', {
        credentials: 'include',
        headers: {
          'Accept': 'application/json'
        }
      });
      
      console.log('Flow response status:', flowResponse.status);
      console.log('Flow response headers:', Object.fromEntries(flowResponse.headers.entries()));
      
      if (!flowResponse.ok) {
        const errorText = await flowResponse.text();
        throw new Error(`Flow request failed: ${flowResponse.status} - ${errorText.substring(0, 200)}`);
      }
      
      const flow = await flowResponse.json();
      console.log('Flow:', flow);

      // 2. Submit login through Next.js proxy
      console.log('Step 2: Submitting login...');
      const csrfToken = flow.ui.nodes.find(n => n.attributes.name === 'csrf_token')?.attributes.value;
      console.log('CSRF token:', csrfToken);
      
      const loginData = {
        method: 'password',
        identifier: '221549137@m.gduf.edu.cn',
        password: 'mc666333',
        csrf_token: csrfToken
      };
      console.log('Login data:', loginData);
      
      const loginResponse = await fetch(`/auth/self-service/login/flows/${flow.id}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(loginData)
      });

      console.log('Login response status:', loginResponse.status);
      console.log('Login response headers:', Object.fromEntries(loginResponse.headers.entries()));
      
      if (!loginResponse.ok) {
        const errorText = await loginResponse.text();
        throw new Error(`Login request failed: ${loginResponse.status} - ${errorText.substring(0, 200)}`);
      }
      
      const loginResult = await loginResponse.json();
      console.log('Login result:', loginResult);
      
      // 3. Check cookies immediately and after delay
      console.log('Cookies immediately:', document.cookie);
      setTimeout(() => {
        console.log('Cookies after 100ms:', document.cookie);
        setCookies(document.cookie);
      }, 100);

      setResult(JSON.stringify(loginResult, null, 2));
    } catch (error) {
      console.error('Error:', error);
      setResult('Error: ' + error.message);
    }
  };

  return (
    <div style={{ padding: '20px' }}>
      <h1>Direct Auth Test</h1>
      <button onClick={testDirectLogin}>Test Direct Login</button>
      <button onClick={testAPI} style={{ marginLeft: '10px' }}>Test API Call</button>
      
      <div>
        <h3>Cookies:</h3>
        <pre>{cookies}</pre>
      </div>
      
      <div>
        <h3>Auth Result:</h3>
        <pre>{result}</pre>
      </div>
      
      <div>
        <h3>API Result:</h3>
        <pre>{apiResult}</pre>
      </div>
    </div>
  );
}