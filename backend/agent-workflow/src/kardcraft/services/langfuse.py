import os
import atexit

try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None

from kardcraft.utils.logger import logger

# Get configuration from environment
public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
secret_key = os.getenv("LANGFUSE_SECRET_KEY")
host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

# Determine if Langfuse should be enabled
enabled = bool(public_key and secret_key)

logger.debug(f"🔍 Langfuse Environment Check:")
logger.debug(f"  - Public Key: {'✅ Set' if public_key else '❌ Missing'}")
logger.debug(f"  - Secret Key: {'✅ Set' if secret_key else '❌ Missing'}")
logger.debug(f"  - Host: {host}")
logger.debug(f"  - Enabled: {enabled}")

# Initialize client using singleton pattern
if enabled:
    logger.debug(f"🔍 Initializing Langfuse with host: {host}")
    try:
        # Initialize with constructor arguments (recommended approach)
        # Disable SSL verification for local/development environments if needed
        import httpx
        # Use SSL verification by default, but disable if SSL issues are detected
        try:
            httpx_client = httpx.Client(verify=True)
            # Test SSL connection
            httpx_client.get("https://httpbin.org/get", timeout=2)
        except Exception as ssl_error:
            logger.debug(f"SSL verification failed, disabling: {ssl_error}")
            httpx_client = httpx.Client(verify=False)
        
        langfuse = Langfuse(  # pyright: ignore[reportCallIssue]
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            httpx_client=httpx_client
        )
        logger.info(f"✅ Langfuse initialized successfully - Host: {host}")
        logger.info(f"🔍 Langfuse Public Key: {public_key[:8]}...{public_key[-4:] if len(public_key) > 12 else public_key}")  # pyright: ignore[reportOptionalSubscript, reportArgumentType]
        
        # Test the connection
        try:
            logger.debug(f"🔍 Testing authentication with {host}...")
            auth_result = langfuse.auth_check()
            if auth_result:
                logger.info(f"🔗 Langfuse authentication successful with {host}")
            else:
                logger.warning(f"❌ Langfuse authentication failed with {host}")
        except Exception as auth_error:
            logger.warning(f"⚠️ Langfuse auth check failed: {auth_error}")
            
            # Try alternative host if authentication fails
            if "us.cloud.langfuse.com" in host:
                logger.info("🔄 Trying EU host as fallback...")
                fallback_host = "https://cloud.langfuse.com"
            elif "cloud.langfuse.com" in host and "us." not in host:
                logger.info("🔄 Trying US host as fallback...")
                fallback_host = "https://us.cloud.langfuse.com"
            else:
                fallback_host = None
            
            if fallback_host:
                try:
                    logger.info(f"🔄 Testing fallback host: {fallback_host}")
                    langfuse_fallback = Langfuse(  # pyright: ignore[reportCallIssue]
                        public_key=public_key,
                        secret_key=secret_key,
                        host=fallback_host,
                        httpx_client=httpx_client
                    )
                    auth_result_fallback = langfuse_fallback.auth_check()
                    if auth_result_fallback:
                        logger.info(f"✅ Fallback host authentication successful! Switching to {fallback_host}")
                        langfuse = langfuse_fallback
                        host = fallback_host
                        # Update the global host for URL generation
                        globals()['host'] = fallback_host
                    else:
                        logger.warning(f"❌ Fallback host {fallback_host} authentication also failed")
                except Exception as fallback_error:
                    logger.warning(f"⚠️ Fallback host {fallback_host} also failed: {fallback_error}")

        # Register shutdown hook for clean exit
        atexit.register(langfuse.shutdown)

    except Exception as e:
        logger.error(f"❌ Failed to initialize Langfuse: {e}")
        # Create disabled instance as fallback with SSL handling
        try:
            import httpx
            httpx_client = httpx.Client(verify=False)
            langfuse = Langfuse(enabled=False, httpx_client=httpx_client)  # pyright: ignore[reportCallIssue]
        except Exception:
            # Ultimate fallback - create a mock client
            class MockLangfuse:  # pyright: ignore[reportRedeclaration]
                def __init__(self):
                    self.enabled = False
                def trace(self, **kwargs): return MockTrace()
                def generation(self, **kwargs): return MockGeneration()
                def span(self, **kwargs): return MockSpan()
                def event(self, **kwargs): pass
                def flush(self): pass
                def shutdown(self): pass
                def auth_check(self): return False
            
            class MockTrace:  # pyright: ignore[reportRedeclaration]
                def __init__(self): 
                    self.id = "mock-trace-id"
                
                def __getattr__(self, name):
                    # Return a no-op function for any method call
                    def no_op(*args, **kwargs):
                        pass
                    return no_op
            class MockGeneration:  # pyright: ignore[reportRedeclaration]
                def __init__(self): 
                    self.id = "mock-generation-id"
                
                def __getattr__(self, name):
                    # Return a no-op function for any method call
                    def no_op(*args, **kwargs):
                        pass
                    return no_op
            class MockSpan:  # pyright: ignore[reportRedeclaration]
                def __init__(self): 
                    self.id = "mock-span-id"
                
                def __getattr__(self, name):
                    # Return a no-op function for any method call
                    def no_op(*args, **kwargs):
                        pass
                    return no_op
            
            langfuse = MockLangfuse()
        enabled = False
else:
    logger.debug("⚠️ Langfuse disabled - missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY")
    # Create mock client for disabled state
    class MockLangfuse:
        def __init__(self):
            self.enabled = False
        def trace(self, **kwargs): return MockTrace()
        def generation(self, **kwargs): return MockGeneration()
        def span(self, **kwargs): return MockSpan()
        def event(self, **kwargs): pass
        def flush(self): pass
        def shutdown(self): pass
        def auth_check(self): return False
    
    class MockTrace:
        def __init__(self): 
            self.id = "mock-trace-id"
        
        def __getattr__(self, name):
            # Return a no-op function for any method call
            def no_op(*args, **kwargs):
                pass
            return no_op
    class MockGeneration:
        def __init__(self): 
            self.id = "mock-generation-id"
        
        def __getattr__(self, name):
            # Return a no-op function for any method call
            def no_op(*args, **kwargs):
                pass
            return no_op
    class MockSpan:
        def __init__(self): 
            self.id = "mock-span-id"
        
        def __getattr__(self, name):
            # Return a no-op function for any method call
            def no_op(*args, **kwargs):
                pass
            return no_op
    
    langfuse = MockLangfuse()

def get_langfuse_client():
    """
    Get the Langfuse client instance.
    In langfuse v2.x, we return the global instance.
    """
    return langfuse
