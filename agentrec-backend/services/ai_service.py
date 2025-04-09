# agentrec-backend/services/ai_service.py
import logging
# Azure/Langchain Imports
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_community.embeddings import OllamaEmbeddings
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field, validator
# Config
from ..config import Config # Relative import

logging.basicConfig(level=logging.INFO)

# Define Standard Internal Semantic Names (Must match parser output)
INTERNAL_ID = 'internal_id'
INTERNAL_DATE = 'internal_date'
INTERNAL_AMOUNT = 'internal_amount'
INTERNAL_DESC = 'internal_description'
# Add others if defined and used in mappings (e.g., INTERNAL_REF1)

# Define Pydantic Model for Expected Output
class ReconciliationOutput(BaseModel):
    status: str = Field(description="Reconciliation status: Must be one of 'Matched', 'Partial Match', or 'Exception'.")
    exception_type: str | None = Field(description="Specific exception type based ONLY on KB Rules (e.g., 'Amount Mismatch', 'Date Tolerance') or null if status is 'Matched'.")
    reason: str = Field(description="Brief explanation referencing the specific KB Rule(s) used for the conclusion.")
    @validator('status')
    def status_must_be_valid(cls, field):
        if field not in ["Matched", "Partial Match", "Exception"]: raise ValueError("status must be 'Matched', 'Partial Match', or 'Exception'")
        return field

# --- Initialize LLM and Embeddings (attempt once globally) ---
llm = None
embeddings = None
# Initialize LLM (Keep AzureChatOpenAI if applicable)
if Config.AZURE_OPENAI_ENDPOINT and Config.AZURE_OPENAI_API_KEY and Config.AZURE_OPENAI_API_VERSION:
    try:
        logging.info(f"Initializing AzureChatOpenAI...")
        llm = AzureChatOpenAI(
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT, api_key=Config.AZURE_OPENAI_API_KEY,
            api_version=Config.AZURE_OPENAI_API_VERSION, azure_deployment=Config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
            temperature=0, max_tokens=350 )
        logging.info("AzureChatOpenAI initialized.")
    except Exception as e: logging.error(f"Error initializing AzureChatOpenAI: {e}", exc_info=True)
else: logging.warning("Skipping Azure OpenAI LLM initialization due to missing config.")


# --- Initialize Ollama Embeddings ---
if Config.OLLAMA_BASE_URL and Config.OLLAMA_EMBEDDING_MODEL_NAME:
    try:
        logging.info(f"Initializing OllamaEmbeddings with base_url: {Config.OLLAMA_BASE_URL} and model: {Config.OLLAMA_EMBEDDING_MODEL_NAME}")
        embeddings = OllamaEmbeddings(
            base_url=Config.OLLAMA_BASE_URL,
            model=Config.OLLAMA_EMBEDDING_MODEL_NAME
            # Add other Ollama parameters if needed (e.g., num_gpu, headers)
        )
        # Optional: Add a quick test call, though initialization doesn't guarantee connection yet
        # embeddings.embed_query("test")
        logging.info("OllamaEmbeddings initialized.")
    except Exception as e:
        logging.error(f"Error initializing OllamaEmbeddings: {e}", exc_info=True)
else:
    logging.warning("Skipping Ollama Embeddings initialization due to missing config.")
# --- End Embeddings Initialization ---

# --- Main Function to Call ---
def get_reconciliation_status(source_tx_internal, target_tx_internal, kb_retriever, prompt_template_str):
    """ Uses the AI RAG chain with specific KB/Prompt to determine status. """
    if not llm or not embeddings:
        logging.error("AI Service LLM or Embeddings not available.")
        return { "status": "Error", "exception_type": "AI Service Unavailable", "reason": "LLM/Embeddings service not initialized." }
    if not kb_retriever:
        logging.error("AI Service Knowledge Base Retriever not available for this call.")
        return { "status": "Error", "exception_type": "AI Service Unavailable", "reason": "Knowledge Base retriever failed to initialize." }
    if not prompt_template_str:
        logging.error("AI Service Prompt Template string is missing.")
        return { "status": "Error", "exception_type": "AI Service Unavailable", "reason": "Prompt template missing." }

    try:
        template_core = """
        You are an expert financial reconciliation agent... [Intro text as before] ...

        **Knowledge Base Rules (Use ONLY these):**
        ---------------------
        {context}
        ---------------------

        **Source Transaction:**
        ID: {{{internal_id_source}}}
        Date: {{{internal_date_source}}}
        Amount: {{{internal_amount_source}}}
        Description: {{{internal_description_source}}}

        **Target Transaction:**
        ID: {{{internal_id_target}}}
        Date: {{{internal_date_target}}}
        Amount: {{{internal_amount_target}}}
        Description: {{{internal_description_target}}}

        **Instructions:**
        1. Carefully analyze the Source and Target transaction details.
        2. Apply *only* the rules provided in the 'Knowledge Base Rules' section. Do not use any other external knowledge or assumptions.
        3. Determine the reconciliation status: 'Matched', 'Partial Match', or 'Exception'.
        4. **For ALL statuses ('Matched', 'Partial Match', 'Exception'), provide a brief 'Reason' explaining *which specific Knowledge Base rule(s)* led to your conclusion.** (e.g., "Exact match on amount and date per Rule KB-BG-003", "Amount difference within tolerance per Rule KB-BG-004", "Date difference exceeds tolerance per Rule KB-BG-102").
        5. If 'Exception' or 'Partial Match', *also* specify the 'Exception Type' based *strictly* on the KB Rules (e.g., 'Amount Mismatch', 'Date Tolerance'). If status is 'Matched', 'Exception Type' should be null.
        6. **CRITICAL: Your entire response must be ONLY the valid JSON object specified below.**

        {format_instructions}

        **Analysis Result (JSON Object Only):**
        """
        # --- Dynamically create parser and prompt ---
        output_parser = JsonOutputParser(pydantic_object=ReconciliationOutput)
        try:
            prompt = ChatPromptTemplate.from_template(
                prompt_template_str,
                partial_variables={"format_instructions": output_parser.get_format_instructions()}
            )
        except Exception as e_prompt:
            logging.error(f"Error creating prompt template: {e_prompt}", exc_info=True)
            raise ValueError(f"Invalid prompt template structure: {e_prompt}")

        # --- Dynamically create the RAG chain ---
        def format_docs(docs): return "\n\n".join(doc.page_content for doc in docs)

        # Ensure retriever is valid before using it
        if not hasattr(kb_retriever, 'invoke') and not hasattr(kb_retriever, 'get_relevant_documents'):
             raise TypeError("Provided kb_retriever is not a valid LangChain retriever instance.")

        retrieve_context = RunnablePassthrough.assign(
            # Use .get with default '' to handle potentially missing description fields gracefully
            context_input_str=lambda x: (x.get(INTERNAL_DESC + '_source', '') or '') + " " + (x.get(INTERNAL_DESC + '_target', '') or '')
        ) | (lambda x: x['context_input_str']) | kb_retriever | format_docs

        # Define how internal inputs are passed through using .get for safety
        passthrough_inputs = RunnablePassthrough.assign(
             internal_id_source=lambda x: x.get(INTERNAL_ID + '_source'),
             internal_date_source=lambda x: x.get(INTERNAL_DATE + '_source'),
             internal_amount_source=lambda x: x.get(INTERNAL_AMOUNT + '_source'),
             internal_description_source=lambda x: x.get(INTERNAL_DESC + '_source'),
             internal_id_target=lambda x: x.get(INTERNAL_ID + '_target'),
             internal_date_target=lambda x: x.get(INTERNAL_DATE + '_target'),
             internal_amount_target=lambda x: x.get(INTERNAL_AMOUNT + '_target'),
             internal_description_target=lambda x: x.get(INTERNAL_DESC + '_target')
        )

        # Combine context retrieval and passthrough
        rag_chain = RunnableParallel(
            {"context": retrieve_context, "inputs": passthrough_inputs}
        ) | RunnablePassthrough.assign(
             internal_id_source=lambda x: x['inputs']['internal_id_source'],
             internal_date_source=lambda x: x['inputs']['internal_date_source'],
             internal_amount_source=lambda x: x['inputs']['internal_amount_source'],
             internal_description_source=lambda x: x['inputs']['internal_description_source'],
             internal_id_target=lambda x: x['inputs']['internal_id_target'],
             internal_date_target=lambda x: x['inputs']['internal_date_target'],
             internal_amount_target=lambda x: x['inputs']['internal_amount_target'],
             internal_description_target=lambda x: x['inputs']['internal_description_target']
         ) | prompt | llm | output_parser # Chain ends with parser


        # --- Prepare input_data ---
        input_data = {}
        required_internal_keys = [INTERNAL_ID, INTERNAL_DATE, INTERNAL_AMOUNT, INTERNAL_DESC] # Extend if needed
        for key in required_internal_keys:
            input_data[key + "_source"] = str(source_tx_internal.get(key, 'N/A')) # Use .get and str()
            input_data[key + "_target"] = str(target_tx_internal.get(key, 'N/A'))

        logging.debug(f"Invoking dynamic RAG chain with input: {input_data}")

        # --- Invoke Chain ---
        result_json = rag_chain.invoke(input_data) # Output parser returns dict
        logging.debug(f"Parsed AI Response: {result_json}")

        # --- Validate Parsed Output ---
        if not isinstance(result_json, dict) or 'status' not in result_json:
            raise ValueError("AI output parser did not return a dictionary with 'status'.")

        valid_statuses = ["Matched", "Partial Match", "Exception"]
        if result_json['status'] not in valid_statuses:
            logging.warning(f"AI returned invalid status: {result_json['status']}. Treating as Exception.")
            result_json['reason'] = f"AI invalid status '{result_json['status']}'. Original: {result_json.get('reason', 'N/A')}"
            result_json['status'] = "Exception"; result_json['exception_type'] = "AI Invalid Status"

        result_json.setdefault('exception_type', None)
        result_json.setdefault('reason', "N/A")

        logging.info(f"AI Analysis Result: Status={result_json['status']}, Type={result_json['exception_type']}")
        return result_json

    except Exception as e:
        logging.error(f"Error in get_reconciliation_status: {e}", exc_info=True)
        return { "status": "Error", "exception_type": "AI Processing Error", "reason": f"Core AI processing/parsing failed: {e}" }