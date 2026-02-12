import React, {useEffect, useState} from 'react'
import { useClerk, useUser } from '@clerk/clerk-react'

export default function Home(){
  const clerk = useClerk()
  const { isLoaded, isSignedIn } = useUser()
  const [redirecting, setRedirecting] = useState(false)

  useEffect(()=>{
    if(!isLoaded) return
    
    if(!isSignedIn){
      window.location.href = '/sign-in'
      return
    }

    const redirectToStreamlit = async () => {
      try{
        setRedirecting(true)
        // Get the session token without specifying a template
        const token = await clerk.session?.getToken()
        if(token){
          const streamlitUrl = 'http://localhost:8502'
          console.log('Redirecting to Streamlit with token')
          window.location.href = `${streamlitUrl}?session_token=${encodeURIComponent(token)}`
        }
      }catch(err){
        console.error('Failed to get token:', err)
        setRedirecting(false)
      }
    }

    redirectToStreamlit()
  }, [isLoaded, isSignedIn, clerk])

  return (
    <div style={{padding: '2rem', textAlign: 'center'}}>
      {redirecting ? (
        <>
          <h2>✅ Signed in successfully!</h2>
          <p>Redirecting to PDF Chat...</p>
        </>
      ) : (
        <>
          <h2>Loading...</h2>
          <p>Please wait...</p>
        </>
      )}
    </div>
  )
}
