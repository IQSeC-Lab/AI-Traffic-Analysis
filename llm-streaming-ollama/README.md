# LLM interaction using ollama
In this experimental setting, we are going to be recreating the setup of the paper "LLMs Have Rhythm: Fingerprinting Large Language Models Using Inter-Token Times and Network Traffic Analysis"

In this case instead of using a custom inference server with FastAPI, we are going to be using the default ollama image.The second change we have done is replacing the hugginface models for ollama ready models, these models can be found on the following page:

[Ollama Model Search](https://ollama.com/search)

## Downloading images:
To download the images onto the ollama do the following:
```Bash
docker run -it --rm \
  --gpus all \
  -v "$(pwd)/ollama_models:/root/.ollama" \
  --name ollama-pull \
  --entrypoint /bin/sh \
  ollama/ollama
```
and inside the image do the following:
```
ollama pull gemma:2b
ollama pull gemma2:2b
ollama pull gemma:7b
ollama pull gemma2:9b
ollama pull llama2:7b
ollama pull mistral:7b

ollama pull image
```

## Executing the program
To execute the pipeline make sure to have the images downloaded and on the main_ollama.py change the variable:
```
OLLAMA_MODELS = [...]
```
with the models you are currently using. also, prompts can be changed, to change the prompts refer to the variable:
```
PROMPTS = [...]
```

Diagram:
<Insert Diagram>


