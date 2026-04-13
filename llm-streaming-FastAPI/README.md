# LLM interaction using FastAPI server
In this experimental setting, we are going to implement our own inference server with the capability of streaming the token just like chatgpt. This server supports the functionality of using hugginface images.


## Downloading images:
To download the images use the script `downloader.sh` and modify the variable of `MODELS` accordingly. Also make sure to put a huggingface api on the downloader.py args. this is to have faster download bandwidth.

## Executing pipeline
The main script of the pipeline is `main.py`, this is the orquestrator that we are going to be using for the automatic llm prompting.

Orchestrates the full experiment:
  - Builds llm-toolbox Docker image
  - Creates isolated internal Docker network (llm-net)
  - Validates model is pre-downloaded on host
  - For each prompt:
      1. Starts a fresh inference container  (new conversation)
      2. Starts a sidecar tcpdump container  (captures only that container's traffic)
      3. Sends the prompt via a client container inside llm-net
      4. Saves PCAP + logs, tears everything down
	  
to change the Model to evaluate, modify the variable `MODEL`. everything is automatic in a isolated network.

Diagram:
<Insert Diagram>


