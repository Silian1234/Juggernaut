Shader "Hidden/Juggernaut/ThermalOutline"
{
    Properties
    {
        _OutlineColor ("Outline Color", Color) = (1, 0, 0, 1)
    }
    SubShader
    {
        Pass
        {
            Cull Off
            ZWrite Off
            ZTest Always
            ColorMask RGB
            Blend SrcAlpha OneMinusSrcAlpha

            CGPROGRAM
            #pragma target 3.5
            #pragma vertex Vert
            #pragma fragment Frag
            #include "UnityCG.cginc"

            sampler2D _JuggernautMask;
            float4 _JuggernautMask_TexelSize;
            fixed4 _OutlineColor;

            struct Varyings
            {
                float4 position : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            Varyings Vert(uint vertexID : SV_VertexID)
            {
                Varyings output;
                output.uv = float2((vertexID << 1) & 2, vertexID & 2);
                output.position = float4(output.uv * 2 - 1, 0, 1);
                #if UNITY_UV_STARTS_AT_TOP
                    output.uv.y = 1 - output.uv.y;
                #endif
                return output;
            }

            fixed4 Frag(Varyings input) : SV_Target
            {
                clip(tex2D(_JuggernautMask, input.uv).r - 0.5);
                float2 stepUV = _JuggernautMask_TexelSize.xy;
                float neighbor = min(
                    min(tex2D(_JuggernautMask, input.uv + float2(stepUV.x, 0)).r,
                        tex2D(_JuggernautMask, input.uv - float2(stepUV.x, 0)).r),
                    min(tex2D(_JuggernautMask, input.uv + float2(0, stepUV.y)).r,
                        tex2D(_JuggernautMask, input.uv - float2(0, stepUV.y)).r));
                // Use an inner contour so that foreground geometry stays untouched.
                clip(0.5 - neighbor);
                return _OutlineColor;
            }
            ENDCG
        }
    }
    Fallback Off
}
