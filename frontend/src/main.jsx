import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ClerkProvider, SignedIn } from '@clerk/clerk-react'
import SignInPage from './pages/SignIn'
import SignUpPage from './pages/SignUp'
import Home from './pages/Home'

const clerkPubKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

function App(){
  return (
    <ClerkProvider publishableKey={clerkPubKey}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/sign-in" replace/>} />
          <Route path="/sign-in" element={<SignInPage/>} />
          <Route path="/sign-in/*" element={<SignInPage/>} />
          <Route path="/sign-up" element={<SignUpPage/>} />
          <Route path="/sign-up/*" element={<SignUpPage/>} />
          <Route 
            path="/dashboard" 
            element={
              <SignedIn>
                <Home />
              </SignedIn>
            } 
          />
        </Routes>
      </BrowserRouter>
    </ClerkProvider>
  )
}

createRoot(document.getElementById('root')).render(<App />)
